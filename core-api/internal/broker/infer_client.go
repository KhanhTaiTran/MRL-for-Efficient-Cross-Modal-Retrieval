package broker

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"time"
)

// InferClient communicates with the Python FastAPI Inference Service over HTTP.
type InferClient struct {
	baseURL    string
	httpClient *http.Client
}

func NewInferClient(baseURL string, timeout time.Duration) *InferClient {
	return &InferClient{
		baseURL: baseURL,
		httpClient: &http.Client{
			Timeout: timeout,
		},
	}
}

// InferSearchResult represents an item returned by the Python worker.
type InferSearchResult struct {
	ProductID        string  `json:"product_id"`
	CatalogProductID string  `json:"catalog_product_id,omitempty"`
	VectorID         int     `json:"vector_id"`
	SimilarityScore  float64 `json:"similarity_score"`
	Caption          string  `json:"caption"`
}

// InferSearchConfig represents configuration echo from worker.
type InferSearchConfig struct {
	RequestedDim int    `json:"requested_dim"`
	SearchMode   string `json:"search_mode"`
	Stage1Dim    int    `json:"stage1_dim"`
	Stage2Dim    *int   `json:"stage2_dim"`
	AQEEnabled   bool   `json:"aqe_enabled"`
}

// InferTiming represents granular inference latency breakdown.
type InferTiming struct {
	EncodeMs      float64 `json:"encode_ms"`
	AQEMs         float64 `json:"aqe_ms"`
	Stage1Ms      float64 `json:"stage1_ms"`
	RerankMs      float64 `json:"rerank_ms"`
	WorkerTotalMs float64 `json:"worker_total_ms"`
}

// InferResponse is the top-level JSON response from the Python worker.
type InferResponse struct {
	Status       string              `json:"status"`
	IndexVersion string              `json:"index_version"`
	Data         []InferSearchResult `json:"data"`
	SearchConfig InferSearchConfig   `json:"search_config"`
	Timing       InferTiming         `json:"timing"`
	Message      string              `json:"message,omitempty"`
}

// SearchConfig holds user-specified retrieval parameters.
type SearchConfig struct {
	MRLDimension int
	SearchMode   string // "direct" or "adaptive"
}

// SearchByText sends text query to POST /infer/search/text
func (c *InferClient) SearchByText(ctx context.Context, query string, cfg SearchConfig) (*InferResponse, error) {
	var buf bytes.Buffer
	w := multipart.NewWriter(&buf)
	if err := w.WriteField("query", query); err != nil {
		return nil, fmt.Errorf("failed to write query field: %w", err)
	}
	if err := w.WriteField("mrl_dimension", fmt.Sprintf("%d", cfg.MRLDimension)); err != nil {
		return nil, fmt.Errorf("failed to write mrl_dimension field: %w", err)
	}
	if err := w.WriteField("search_mode", cfg.SearchMode); err != nil {
		return nil, fmt.Errorf("failed to write search_mode field: %w", err)
	}
	if err := w.Close(); err != nil {
		return nil, fmt.Errorf("failed to close multipart writer: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, "POST", c.baseURL+"/infer/search/text", &buf)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("Content-Type", w.FormDataContentType())

	return c.do(req)
}

// SearchByImage sends uploaded image to POST /infer/search/image
func (c *InferClient) SearchByImage(ctx context.Context, imageBytes []byte, filename string, cfg SearchConfig) (*InferResponse, error) {
	var buf bytes.Buffer
	w := multipart.NewWriter(&buf)
	part, err := w.CreateFormFile("image", filename)
	if err != nil {
		return nil, fmt.Errorf("failed to create form file: %w", err)
	}
	if _, err = io.Copy(part, bytes.NewReader(imageBytes)); err != nil {
		return nil, fmt.Errorf("failed to write image bytes: %w", err)
	}
	if err := w.WriteField("mrl_dimension", fmt.Sprintf("%d", cfg.MRLDimension)); err != nil {
		return nil, fmt.Errorf("failed to write mrl_dimension field: %w", err)
	}
	if err := w.WriteField("search_mode", cfg.SearchMode); err != nil {
		return nil, fmt.Errorf("failed to write search_mode field: %w", err)
	}
	if err := w.Close(); err != nil {
		return nil, fmt.Errorf("failed to close multipart writer: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, "POST", c.baseURL+"/infer/search/image", &buf)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("Content-Type", w.FormDataContentType())

	return c.do(req)
}

// GetConfig fetches the active configuration from GET /infer/config
func (c *InferClient) GetConfig(ctx context.Context) (map[string]any, error) {
	req, err := http.NewRequestWithContext(ctx, "GET", c.baseURL+"/infer/config", nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("inference API unreachable: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, &HTTPError{Status: resp.StatusCode, Message: "Inference configuration unavailable"}
	}

	var result map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("failed to decode inference config response: %w", err)
	}
	return result, nil
}

// Health checks the service status from GET /infer/health
func (c *InferClient) Health(ctx context.Context) (map[string]any, error) {
	req, err := http.NewRequestWithContext(ctx, "GET", c.baseURL+"/infer/health", nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("inference API unreachable: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, &HTTPError{Status: resp.StatusCode, Message: "Inference configuration unavailable"}
	}

	var result map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("failed to decode inference health response: %w", err)
	}
	return result, nil
}

func (c *InferClient) do(req *http.Request) (*InferResponse, error) {
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("inference service request failed: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read inference response body: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		var errResp struct {
			Detail  any    `json:"detail"`
			Message string `json:"message"`
		}
		_ = json.Unmarshal(respBody, &errResp)
		msg := errResp.Message
		if msg == "" && errResp.Detail != nil {
			msg = fmt.Sprintf("%v", errResp.Detail)
		}
		if msg == "" {
			msg = string(respBody)
		}
		return nil, &HTTPError{Status: resp.StatusCode, Message: msg}
	}

	var result InferResponse
	if err := json.Unmarshal(respBody, &result); err != nil {
		return nil, fmt.Errorf("failed to parse inference response JSON: %w (body: %s)", err, string(respBody))
	}

	if result.Status != "success" {
		return nil, fmt.Errorf("inference service returned error: %s", result.Message)
	}

	return &result, nil
}

type HTTPError struct {
	Status  int
	Message string
}

func (e *HTTPError) Error() string { return e.Message }
func ErrorStatus(err error) int {
	var upstream *HTTPError
	if errors.As(err, &upstream) {
		return upstream.Status
	}
	var timeout interface{ Timeout() bool }
	if errors.Is(err, context.DeadlineExceeded) || (errors.As(err, &timeout) && timeout.Timeout()) {
		return http.StatusGatewayTimeout
	}
	return http.StatusServiceUnavailable
}
