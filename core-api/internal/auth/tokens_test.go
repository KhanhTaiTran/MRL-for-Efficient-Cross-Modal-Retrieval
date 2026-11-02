package auth

import (
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

func TestAccessTokenValidation(t *testing.T) {
	secret := "unit-test-key-at-least-thirty-two-bytes"
	valid, err := Sign(secret, "user-id", "session-family", time.Now())
	if err != nil {
		t.Fatal(err)
	}
	claims, err := Parse(secret, valid)
	if err != nil || claims.Subject != "user-id" || claims.FamilyID != "session-family" {
		t.Fatalf("valid session rejected: %v", err)
	}
	if _, err = Parse("different-signing-key", valid); err == nil {
		t.Fatal("wrong key accepted")
	}
	expired, _ := Sign(secret, "user-id", "session-family", time.Now().Add(-time.Hour))
	if _, err = Parse(secret, expired); err == nil {
		t.Fatal("expired token accepted")
	}
	unsigned, _ := jwt.NewWithClaims(jwt.SigningMethodNone, claims).SignedString(jwt.UnsafeAllowNoneSignatureType)
	if _, err = Parse(secret, unsigned); err == nil {
		t.Fatal("unsigned token accepted")
	}
	wrongAudience := *claims
	wrongAudience.Audience = jwt.ClaimStrings{"other-app"}
	wrong, _ := jwt.NewWithClaims(jwt.SigningMethodHS256, wrongAudience).SignedString([]byte(secret))
	if _, err = Parse(secret, wrong); err == nil {
		t.Fatal("wrong audience accepted")
	}
}

func TestOTPIsPaddedAndBoundToUserAndPurpose(t *testing.T) {
	for i := 0; i < 1000; i++ {
		code, err := OTP()
		if err != nil {
			t.Fatal(err)
		}
		if len(code) != 6 {
			t.Fatalf("invalid code width: %q", code)
		}
	}
	hash := OTPHash("secret", "user-a", "verify_email", "123456")
	if hash == OTPHash("secret", "user-b", "verify_email", "123456") || hash == OTPHash("secret", "user-a", "reset_password", "123456") {
		t.Fatal("OTP hash is not bound to user and purpose")
	}
}
