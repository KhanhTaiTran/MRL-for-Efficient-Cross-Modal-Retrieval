package auth

import (
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"math/big"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

const AccessLifetime = 15 * time.Minute
const RefreshLifetime = 7 * 24 * time.Hour
const Issuer = "aurafind"

type Claims struct {
	FamilyID string `json:"sid"`
	jwt.RegisteredClaims
}

func RandomToken() (string, error) {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return hex.EncodeToString(b), nil
}

func OTP() (string, error) {
	n, err := rand.Int(rand.Reader, big.NewInt(1000000))
	if err != nil {
		return "", err
	}
	return fmt.Sprintf("%06d", n.Int64()), nil
}

func Hash(token string) string {
	h := sha256.Sum256([]byte(token))
	return hex.EncodeToString(h[:])
}

func OTPHash(secret, userID, purpose, code string) string {
	h := hmac.New(sha256.New, []byte(secret))
	h.Write([]byte(userID + ":" + purpose + ":" + code))
	return hex.EncodeToString(h.Sum(nil))
}

func Sign(secret, userID, familyID string, now time.Time) (string, error) {
	claims := Claims{FamilyID: familyID, RegisteredClaims: jwt.RegisteredClaims{
		Subject: userID, Issuer: Issuer, Audience: jwt.ClaimStrings{"aurafind-web"},
		IssuedAt: jwt.NewNumericDate(now), ExpiresAt: jwt.NewNumericDate(now.Add(AccessLifetime)),
	}}
	return jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString([]byte(secret))
}

func Parse(secret, token string) (*Claims, error) {
	claims := &Claims{}
	parsed, err := jwt.ParseWithClaims(token, claims, func(t *jwt.Token) (any, error) {
		return []byte(secret), nil
	}, jwt.WithValidMethods([]string{"HS256"}), jwt.WithIssuer(Issuer),
		jwt.WithAudience("aurafind-web"), jwt.WithExpirationRequired())
	if err != nil || !parsed.Valid || claims.Subject == "" || claims.FamilyID == "" {
		return nil, errors.New("invalid access token")
	}
	return claims, nil
}
