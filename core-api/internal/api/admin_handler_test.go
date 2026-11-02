package api

import (
	"bytes"
	"github.com/gin-gonic/gin"
	"image"
	"image/jpeg"
	"image/png"
	"net/http/httptest"
	"testing"
)

func TestAdminRoleGuard(t *testing.T) {
	gin.SetMode(gin.TestMode)
	for _, role := range []string{"customer", "admin"} {
		r := gin.New()
		r.Use(func(c *gin.Context) { c.Set("user", User{Role: role}) }, requireAdmin)
		r.GET("/", func(c *gin.Context) { c.Status(204) })
		response := httptest.NewRecorder()
		r.ServeHTTP(response, httptest.NewRequest("GET", "/", nil))
		expected := 403
		if role == "admin" {
			expected = 204
		}
		if response.Code != expected {
			t.Fatalf("%s got %d", role, response.Code)
		}
	}
}
func TestProductImageNormalization(t *testing.T) {
	if _, err := normalizeProductImage([]byte("<svg onload='alert(1)'/>")); err == nil {
		t.Fatal("SVG accepted")
	}
	for _, format := range []string{"png", "jpeg"} {
		var original bytes.Buffer
		img := image.NewRGBA(image.Rect(0, 0, 10, 20))
		if format == "png" {
			png.Encode(&original, img)
		} else {
			jpeg.Encode(&original, img, nil)
		}
		normalized, err := normalizeProductImage(original.Bytes())
		if err != nil {
			t.Fatal(err)
		}
		config, kind, err := image.DecodeConfig(bytes.NewReader(normalized))
		if err != nil || kind != "png" || config.Width != 10 || config.Height != 20 {
			t.Fatal("normalization failed", err)
		}
	}
}
