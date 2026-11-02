package api

import (
	"context"
	"crypto/hmac"
	"errors"
	"log"
	"net/http"
	"net/mail"
	"strings"
	"sync"
	"time"

	"core-api/internal/auth"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
	"golang.org/x/crypto/bcrypt"
)

const refreshCookie = "aurafind_refresh"

type User struct {
	ID       string `json:"id"`
	Email    string `json:"email"`
	Name     string `json:"name"`
	Role     string `json:"role"`
	Verified bool   `json:"is_verified"`
}

type AuthHandler struct {
	db       *pgxpool.Pool
	secret   string
	secure   bool
	origins  map[string]bool
	mailer   auth.Mailer
	mu       sync.Mutex
	attempts map[string]rateWindow
}
type rateWindow struct {
	Start time.Time
	Count int
}
type authInput struct {
	Email    string `json:"email"`
	Name     string `json:"name"`
	Password string `json:"password"`
	Code     string `json:"code"`
}
type session struct {
	AccessToken string `json:"access_token"`
	ExpiresIn   int    `json:"expires_in"`
	User        User   `json:"user"`
}

func NewAuthHandler(db *pgxpool.Pool, secret string, secure bool, origins []string, mailer auth.Mailer) (*AuthHandler, error) {
	if len(secret) < 32 {
		return nil, errors.New("JWT_SECRET must contain at least 32 bytes")
	}
	allowed := map[string]bool{}
	for _, origin := range origins {
		allowed[strings.TrimSpace(origin)] = true
	}
	return &AuthHandler{db: db, secret: secret, secure: secure, origins: allowed, mailer: mailer, attempts: map[string]rateWindow{}}, nil
}

func (h *AuthHandler) RegisterRoutes(r *gin.RouterGroup) {
	a := r.Group("/auth")
	a.Use(h.originGuard)
	a.GET("/me", h.RequireUser(), h.Me)
	a.PATCH("/me", h.RequireUser(), h.UpdateProfile)
	a.POST("/logout", h.Logout)
	a.POST("/refresh", h.Refresh)
	a.Use(h.rateLimit)
	a.POST("/register", h.Register)
	a.POST("/login", h.Login)
	a.POST("/verify-email", h.VerifyEmail)
	a.POST("/resend-verification", h.ResendVerification)
	a.POST("/forgot-password", h.ForgotPassword)
	a.POST("/reset-password", h.ResetPassword)
}

func (h *AuthHandler) originGuard(c *gin.Context) {
	origin := c.GetHeader("Origin")
	_, cookieErr := c.Cookie(refreshCookie)
	if c.Request.Method != "GET" && ((origin != "" && !h.origins[origin]) || (cookieErr == nil && origin == "")) {
		c.AbortWithStatusJSON(403, gin.H{"error": "Request origin is not allowed"})
		return
	}
	c.Header("Cache-Control", "no-store")
	c.Next()
}

func (h *AuthHandler) rateLimit(c *gin.Context) {
	// Single-instance MVP limiter. Persistent per-user OTP limits are enforced separately.
	key := c.ClientIP() + ":" + c.FullPath()
	now := time.Now()
	h.mu.Lock()
	for key, w := range h.attempts {
		if now.Sub(w.Start) > 15*time.Minute {
			delete(h.attempts, key)
		}
	}
	w := h.attempts[key]
	if now.Sub(w.Start) > 15*time.Minute {
		w = rateWindow{Start: now}
	}
	w.Count++
	h.attempts[key] = w
	h.mu.Unlock()
	if w.Count > 40 {
		c.Header("Retry-After", "900")
		c.AbortWithStatusJSON(429, gin.H{"error": "Too many attempts. Please try again later."})
		return
	}
	c.Next()
}

func readAuth(c *gin.Context) (authInput, bool) {
	var input authInput
	c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, 16*1024)
	if !strings.HasPrefix(c.ContentType(), "application/json") || c.ShouldBindJSON(&input) != nil {
		c.JSON(400, gin.H{"error": "A valid JSON request is required"})
		return input, false
	}
	input.Email = strings.ToLower(strings.TrimSpace(input.Email))
	input.Name = strings.TrimSpace(input.Name)
	return input, true
}
func validEmail(email string) bool {
	address, err := mail.ParseAddress(email)
	return err == nil && address.Address == email && len(email) <= 254
}
func validPassword(password string) bool { return len(password) >= 12 && len(password) <= 72 }
func userFrom(row pgx.Row) (User, error) {
	var u User
	err := row.Scan(&u.ID, &u.Email, &u.Name, &u.Role, &u.Verified)
	return u, err
}

const userFields = "id::text,email,name,role,is_verified"

func (h *AuthHandler) fail(c *gin.Context, err error) {
	log.Printf("auth operation failed: %v", err)
	c.JSON(503, gin.H{"error": "Account service is temporarily unavailable. Please try again."})
}

var errOTPLimit = errors.New("OTP request limit")

func (h *AuthHandler) createOTP(ctx context.Context, tx pgx.Tx, u User, purpose string) error {
	var count int
	var recent bool
	if err := tx.QueryRow(ctx, `SELECT count(*),COALESCE(bool_or(created_at>now()-interval '60 seconds'),false) FROM otp_tokens WHERE user_id=$1 AND purpose=$2 AND created_at>now()-interval '1 hour'`, u.ID, purpose).Scan(&count, &recent); err != nil {
		return err
	}
	if recent || count >= 5 {
		return errOTPLimit
	}
	code, err := auth.OTP()
	if err != nil {
		return err
	}
	if _, err = tx.Exec(ctx, "UPDATE otp_tokens SET used=true WHERE user_id=$1 AND purpose=$2 AND NOT used", u.ID, purpose); err != nil {
		return err
	}
	if _, err = tx.Exec(ctx, `INSERT INTO otp_tokens(user_id,code_hash,purpose,expires_at) VALUES($1,$2,$3,now()+interval '10 minutes')`, u.ID, auth.OTPHash(h.secret, u.ID, purpose, code), purpose); err != nil {
		return err
	}
	return h.mailer.SendCode(ctx, u.Email, purpose, code)
}
func (h *AuthHandler) otpError(c *gin.Context, err error) {
	if errors.Is(err, errOTPLimit) {
		c.Header("Retry-After", "60")
		c.JSON(429, gin.H{"error": "Please wait before requesting another code."})
		return
	}
	h.fail(c, err)
}

func (h *AuthHandler) Register(c *gin.Context) {
	in, ok := readAuth(c)
	if !ok {
		return
	}
	if !validEmail(in.Email) || len(in.Name) < 1 || len(in.Name) > 120 || !validPassword(in.Password) {
		c.JSON(400, gin.H{"error": "Enter a valid email, a name and a password of 12–72 bytes."})
		return
	}
	hash, err := bcrypt.GenerateFromPassword([]byte(in.Password), bcrypt.DefaultCost)
	if err != nil {
		h.fail(c, err)
		return
	}
	ctx := c.Request.Context()
	tx, err := h.db.Begin(ctx)
	if err != nil {
		h.fail(c, err)
		return
	}
	defer tx.Rollback(ctx)
	u, err := userFrom(tx.QueryRow(ctx, "INSERT INTO users(email,name,password_hash) VALUES($1,$2,$3) RETURNING "+userFields, in.Email, in.Name, string(hash)))
	if err != nil {
		var pgErr *pgconn.PgError
		if errors.As(err, &pgErr) && pgErr.Code == "23505" {
			c.JSON(409, gin.H{"error": "This email is already registered. Sign in or request another verification code."})
			return
		}
		h.fail(c, err)
		return
	}
	if err = h.createOTP(ctx, tx, u, "verify_email"); err != nil {
		h.otpError(c, err)
		return
	}
	if err = tx.Commit(ctx); err != nil {
		h.fail(c, err)
		return
	}
	c.JSON(201, gin.H{"message": "Check your email for a verification code.", "email": u.Email})
}

func (h *AuthHandler) issue(ctx context.Context, tx pgx.Tx, u User, family string) (session, string, string, error) {
	token, err := auth.RandomToken()
	if err != nil {
		return session{}, "", "", err
	}
	var familyArg any
	if family != "" {
		familyArg = family
	}
	var id string
	err = tx.QueryRow(ctx, `INSERT INTO refresh_tokens(user_id,token_hash,family_id,expires_at) VALUES($1,$2,COALESCE($3::uuid,gen_random_uuid()),$4) RETURNING id::text,family_id::text`, u.ID, auth.Hash(token), familyArg, time.Now().Add(auth.RefreshLifetime)).Scan(&id, &family)
	if err != nil {
		return session{}, "", "", err
	}
	access, err := auth.Sign(h.secret, u.ID, family, time.Now())
	return session{AccessToken: access, ExpiresIn: int(auth.AccessLifetime.Seconds()), User: u}, token, id, err
}
func (h *AuthHandler) setCookie(c *gin.Context, token string) {
	age := int(auth.RefreshLifetime.Seconds())
	if token == "" {
		age = -1
	}
	http.SetCookie(c.Writer, &http.Cookie{Name: refreshCookie, Value: token, Path: "/api/auth", HttpOnly: true, Secure: h.secure, SameSite: http.SameSiteLaxMode, MaxAge: age})
}

func (h *AuthHandler) Login(c *gin.Context) {
	in, ok := readAuth(c)
	if !ok {
		return
	}
	if !validEmail(in.Email) || len(in.Password) > 72 {
		c.JSON(401, gin.H{"error": "Invalid email or password"})
		return
	}
	ctx := c.Request.Context()
	tx, err := h.db.Begin(ctx)
	if err != nil {
		h.fail(c, err)
		return
	}
	defer tx.Rollback(ctx)
	var u User
	var hash string
	err = tx.QueryRow(ctx, "SELECT "+userFields+",COALESCE(password_hash,'') FROM users WHERE lower(email)=$1 FOR UPDATE", in.Email).Scan(&u.ID, &u.Email, &u.Name, &u.Role, &u.Verified, &hash)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		h.fail(c, err)
		return
	}
	if err != nil || bcrypt.CompareHashAndPassword([]byte(hash), []byte(in.Password)) != nil {
		c.JSON(401, gin.H{"error": "Invalid email or password"})
		return
	}
	if !u.Verified {
		c.JSON(403, gin.H{"error": "Verify your email before signing in.", "code": "email_not_verified"})
		return
	}
	result, token, _, err := h.issue(ctx, tx, u, "")
	if err == nil {
		err = tx.Commit(ctx)
	}
	if err != nil {
		h.fail(c, err)
		return
	}
	h.setCookie(c, token)
	c.JSON(200, result)
}

// Caller holds the user row lock; wrong guesses must commit their attempt count.
func (h *AuthHandler) consumeOTP(ctx context.Context, tx pgx.Tx, u User, purpose, code string) (bool, error) {
	var id, hash string
	var attempts int
	var valid bool
	err := tx.QueryRow(ctx, `SELECT id::text,code_hash,attempts,(NOT used AND expires_at>now()) FROM otp_tokens WHERE user_id=$1 AND purpose=$2 ORDER BY created_at DESC LIMIT 1 FOR UPDATE`, u.ID, purpose).Scan(&id, &hash, &attempts, &valid)
	if errors.Is(err, pgx.ErrNoRows) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	if !valid || attempts >= 5 {
		return false, nil
	}
	match := len(code) == 6 && hmac.Equal([]byte(hash), []byte(auth.OTPHash(h.secret, u.ID, purpose, code)))
	_, err = tx.Exec(ctx, "UPDATE otp_tokens SET attempts=attempts+1,used=$2 WHERE id=$1", id, match)
	return match, err
}

func (h *AuthHandler) VerifyEmail(c *gin.Context)   { h.completeOTP(c, "verify_email") }
func (h *AuthHandler) ResetPassword(c *gin.Context) { h.completeOTP(c, "reset_password") }
func (h *AuthHandler) completeOTP(c *gin.Context, purpose string) {
	in, ok := readAuth(c)
	if !ok {
		return
	}
	if !validEmail(in.Email) || (purpose == "reset_password" && !validPassword(in.Password)) {
		c.JSON(400, gin.H{"error": "Enter a valid email and a password of 12–72 bytes."})
		return
	}
	ctx := c.Request.Context()
	tx, err := h.db.Begin(ctx)
	if err != nil {
		h.fail(c, err)
		return
	}
	defer tx.Rollback(ctx)
	u, err := userFrom(tx.QueryRow(ctx, "SELECT "+userFields+" FROM users WHERE lower(email)=$1 FOR UPDATE", in.Email))
	if errors.Is(err, pgx.ErrNoRows) {
		c.JSON(400, gin.H{"error": "Invalid or expired code"})
		return
	}
	if err != nil {
		h.fail(c, err)
		return
	}
	match, err := h.consumeOTP(ctx, tx, u, purpose, in.Code)
	if err != nil {
		h.fail(c, err)
		return
	}
	if !match {
		if err = tx.Commit(ctx); err != nil {
			h.fail(c, err)
			return
		}
		c.JSON(400, gin.H{"error": "Invalid or expired code"})
		return
	}
	if purpose == "reset_password" {
		hash, err := bcrypt.GenerateFromPassword([]byte(in.Password), bcrypt.DefaultCost)
		if err != nil {
			h.fail(c, err)
			return
		}
		if _, err = tx.Exec(ctx, "UPDATE users SET password_hash=$2,updated_at=now() WHERE id=$1", u.ID, string(hash)); err != nil {
			h.fail(c, err)
			return
		}
		if _, err = tx.Exec(ctx, "UPDATE refresh_tokens SET revoked=true WHERE user_id=$1", u.ID); err != nil {
			h.fail(c, err)
			return
		}
		if err = tx.Commit(ctx); err != nil {
			h.fail(c, err)
			return
		}
		h.setCookie(c, "")
		c.JSON(200, gin.H{"message": "Password updated. Sign in with your new password."})
		return
	}
	if _, err = tx.Exec(ctx, "UPDATE users SET is_verified=true,updated_at=now() WHERE id=$1", u.ID); err != nil {
		h.fail(c, err)
		return
	}
	u.Verified = true
	result, token, _, err := h.issue(ctx, tx, u, "")
	if err == nil {
		err = tx.Commit(ctx)
	}
	if err != nil {
		h.fail(c, err)
		return
	}
	h.setCookie(c, token)
	c.JSON(200, result)
}

func (h *AuthHandler) ResendVerification(c *gin.Context) { h.requestOTP(c, "verify_email") }
func (h *AuthHandler) ForgotPassword(c *gin.Context)     { h.requestOTP(c, "reset_password") }
func (h *AuthHandler) requestOTP(c *gin.Context, purpose string) {
	in, ok := readAuth(c)
	if !ok {
		return
	}
	if !validEmail(in.Email) {
		c.JSON(400, gin.H{"error": "Enter a valid email address"})
		return
	}
	ctx := c.Request.Context()
	tx, err := h.db.Begin(ctx)
	if err != nil {
		h.fail(c, err)
		return
	}
	defer tx.Rollback(ctx)
	u, err := userFrom(tx.QueryRow(ctx, "SELECT "+userFields+" FROM users WHERE lower(email)=$1 AND provider='local' FOR UPDATE", in.Email))
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		h.fail(c, err)
		return
	}
	if err == nil && ((purpose == "verify_email" && !u.Verified) || (purpose == "reset_password" && u.Verified)) {
		if err = h.createOTP(ctx, tx, u, purpose); err != nil {
			h.otpError(c, err)
			return
		}
	}
	if err = tx.Commit(ctx); err != nil {
		h.fail(c, err)
		return
	}
	c.JSON(200, gin.H{"message": "If this account is eligible, a code has been sent to its email address."})
}

func (h *AuthHandler) Refresh(c *gin.Context) {
	old, err := c.Cookie(refreshCookie)
	if err != nil || len(old) != 64 {
		h.setCookie(c, "")
		c.JSON(401, gin.H{"error": "Sign in to continue"})
		return
	}
	ctx := c.Request.Context()
	tx, err := h.db.Begin(ctx)
	if err != nil {
		h.fail(c, err)
		return
	}
	defer tx.Rollback(ctx)
	var userID string
	err = tx.QueryRow(ctx, "SELECT user_id::text FROM refresh_tokens WHERE token_hash=$1", auth.Hash(old)).Scan(&userID)
	if errors.Is(err, pgx.ErrNoRows) {
		h.setCookie(c, "")
		c.JSON(401, gin.H{"error": "Session expired"})
		return
	}
	if err != nil {
		h.fail(c, err)
		return
	}
	u, err := userFrom(tx.QueryRow(ctx, "SELECT "+userFields+" FROM users WHERE id=$1 FOR UPDATE", userID))
	if err != nil {
		h.fail(c, err)
		return
	}
	var id, family string
	var revoked, expired bool
	err = tx.QueryRow(ctx, "SELECT id::text,family_id::text,revoked,expires_at<=now() FROM refresh_tokens WHERE token_hash=$1 FOR UPDATE", auth.Hash(old)).Scan(&id, &family, &revoked, &expired)
	if err != nil {
		h.fail(c, err)
		return
	}
	if revoked || expired || !u.Verified {
		if _, err = tx.Exec(ctx, "UPDATE refresh_tokens SET revoked=true WHERE family_id=$1", family); err == nil {
			err = tx.Commit(ctx)
		}
		if err != nil {
			h.fail(c, err)
			return
		}
		h.setCookie(c, "")
		c.JSON(401, gin.H{"error": "Session expired. Sign in again."})
		return
	}
	result, token, newID, err := h.issue(ctx, tx, u, family)
	if err != nil {
		h.fail(c, err)
		return
	}
	if _, err = tx.Exec(ctx, "UPDATE refresh_tokens SET revoked=true,replaced_by=$2 WHERE id=$1", id, newID); err == nil {
		err = tx.Commit(ctx)
	}
	if err != nil {
		h.fail(c, err)
		return
	}
	h.setCookie(c, token)
	c.JSON(200, result)
}

func (h *AuthHandler) Logout(c *gin.Context) {
	if token, err := c.Cookie(refreshCookie); err == nil {
		// Lock the user first, matching login/reset/refresh lock order.
		ctx := c.Request.Context()
		tx, err := h.db.Begin(ctx)
		if err != nil {
			h.fail(c, err)
			return
		}
		defer tx.Rollback(ctx)
		var userID, family string
		err = tx.QueryRow(ctx, "SELECT user_id::text,family_id::text FROM refresh_tokens WHERE token_hash=$1", auth.Hash(token)).Scan(&userID, &family)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			h.fail(c, err)
			return
		}
		if err == nil {
			if _, err = tx.Exec(ctx, "SELECT id FROM users WHERE id=$1 FOR UPDATE", userID); err != nil {
				h.fail(c, err)
				return
			}
			if _, err = tx.Exec(ctx, "UPDATE refresh_tokens SET revoked=true WHERE family_id=$1", family); err != nil {
				h.fail(c, err)
				return
			}
		}
		if err = tx.Commit(ctx); err != nil {
			h.fail(c, err)
			return
		}
	}
	h.setCookie(c, "")
	c.JSON(200, gin.H{"message": "Signed out"})
}

func (h *AuthHandler) RequireUser() gin.HandlerFunc {
	return func(c *gin.Context) {
		header := c.GetHeader("Authorization")
		if !strings.HasPrefix(header, "Bearer ") {
			c.AbortWithStatusJSON(401, gin.H{"error": "Sign in to continue"})
			return
		}
		claims, err := auth.Parse(h.secret, strings.TrimPrefix(header, "Bearer "))
		if err != nil {
			c.AbortWithStatusJSON(401, gin.H{"error": "Session expired"})
			return
		}
		u, err := userFrom(h.db.QueryRow(c.Request.Context(), "SELECT "+userFields+` FROM users u WHERE id=$1 AND is_verified AND EXISTS(SELECT 1 FROM refresh_tokens r WHERE r.user_id=u.id AND r.family_id=$2 AND NOT r.revoked AND r.expires_at>now())`, claims.Subject, claims.FamilyID))
		if errors.Is(err, pgx.ErrNoRows) {
			c.AbortWithStatusJSON(401, gin.H{"error": "Session expired"})
			return
		}
		if err != nil {
			c.AbortWithStatusJSON(503, gin.H{"error": "Account service is temporarily unavailable"})
			return
		}
		c.Set("user", u)
		c.Next()
	}
}
func (h *AuthHandler) Me(c *gin.Context) { c.JSON(200, gin.H{"user": c.MustGet("user").(User)}) }
func (h *AuthHandler) UpdateProfile(c *gin.Context) {
	in, ok := readAuth(c)
	if !ok {
		return
	}
	if len(in.Name) < 1 || len(in.Name) > 120 {
		c.JSON(400, gin.H{"error": "Name must contain 1–120 bytes"})
		return
	}
	u := c.MustGet("user").(User)
	updated, err := userFrom(h.db.QueryRow(c.Request.Context(), "UPDATE users SET name=$2,updated_at=now() WHERE id=$1 RETURNING "+userFields, u.ID, in.Name))
	if err != nil {
		h.fail(c, err)
		return
	}
	c.JSON(200, gin.H{"user": updated})
}
