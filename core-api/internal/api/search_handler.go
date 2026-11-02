package api

import (
	"fmt"
	"io"
	"net/http"
	"strconv"
	"time"

	"core-api/internal/broker"
	"core-api/internal/catalog"
	"core-api/internal/models"
	"github.com/gin-gonic/gin"
)

type SearchHandler struct {
	inferClient *broker.InferClient
	catalog     *catalog.Repository
}

func (h *SearchHandler) WithCatalog(repo *catalog.Repository) *SearchHandler {
	h.catalog = repo
	return h
}

func (h *SearchHandler) respond(c *gin.Context, infer *broker.InferResponse, dim int, elapsed time.Duration, started time.Time) {
	response := buildSearchResponse(infer, dim, elapsed, started)
	if h.catalog != nil {
		enrichStart := time.Now()
		items, err := h.catalog.Enrich(c.Request.Context(), infer.IndexVersion, response.Data)
		if err != nil {
			c.JSON(503, gin.H{"error": "Search catalog is not ready for this index version"})
			return
		}
		response.Data = items
		response.Timing.EnrichMs = roundMs(time.Since(enrichStart).Seconds() * 1000)
		response.Timing.RequestTotalMs = roundMs(time.Since(started).Seconds() * 1000)
	}
	c.JSON(http.StatusOK, response)
}

func NewSearchHandler(inferClient *broker.InferClient) *SearchHandler {
	return &SearchHandler{inferClient: inferClient}
}

// RegisterRoutes registers search endpoints onto the given router group.
func (h *SearchHandler) RegisterRoutes(rg *gin.RouterGroup) {
	rg.POST("/search/text", h.SearchByText)
	rg.POST("/search/image", h.SearchByImage)
	rg.GET("/search/config", h.GetConfig)
}

func (h *SearchHandler) SearchByText(c *gin.Context) {
	requestStart := time.Now()

	query := c.PostForm("query")
	if query == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Please provide a search text with key 'query'"})
		return
	}

	cfg, err := parseSearchConfig(c)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	inferStart := time.Now()
	inferResp, err := h.inferClient.SearchByText(c.Request.Context(), query, cfg)
	inferElapsed := time.Since(inferStart)

	if err != nil {
		c.JSON(broker.ErrorStatus(err), gin.H{"error": "Search service error: " + err.Error()})
		return
	}

	h.respond(c, inferResp, cfg.MRLDimension, inferElapsed, requestStart)
}

func (h *SearchHandler) SearchByImage(c *gin.Context) {
	requestStart := time.Now()
	c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, 10*1024*1024)

	file, header, err := c.Request.FormFile("image")
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "Please upload an image with key 'image'"})
		return
	}
	defer file.Close()

	imageBytes, err := io.ReadAll(file)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to read uploaded image file"})
		return
	}

	cfg, err := parseSearchConfig(c)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	inferStart := time.Now()
	inferResp, err := h.inferClient.SearchByImage(c.Request.Context(), imageBytes, header.Filename, cfg)
	inferElapsed := time.Since(inferStart)

	if err != nil {
		c.JSON(broker.ErrorStatus(err), gin.H{"error": "Search service error: " + err.Error()})
		return
	}

	h.respond(c, inferResp, cfg.MRLDimension, inferElapsed, requestStart)
}

func (h *SearchHandler) GetConfig(c *gin.Context) {
	cfg, err := h.inferClient.GetConfig(c.Request.Context())
	if err != nil {
		c.JSON(broker.ErrorStatus(err), gin.H{"error": "Failed to fetch inference configuration: " + err.Error()})
		return
	}
	c.JSON(http.StatusOK, cfg)
}

func parseSearchConfig(c *gin.Context) (broker.SearchConfig, error) {
	dimStr := c.PostForm("mrl_dimension")
	if dimStr == "" {
		dimStr = c.Query("mrl_dimension")
	}
	if dimStr == "" {
		return broker.SearchConfig{}, fmt.Errorf("missing required field 'mrl_dimension'")
	}

	dim, err := strconv.Atoi(dimStr)
	if err != nil || dim <= 0 {
		return broker.SearchConfig{}, fmt.Errorf("invalid 'mrl_dimension': must be a positive integer")
	}

	mode := c.PostForm("search_mode")
	if mode == "" {
		mode = c.DefaultQuery("search_mode", "adaptive")
	}
	if mode != "direct" && mode != "adaptive" {
		return broker.SearchConfig{}, fmt.Errorf("invalid search_mode")
	}

	return broker.SearchConfig{
		MRLDimension: dim,
		SearchMode:   mode,
	}, nil
}

func buildSearchResponse(
	infer *broker.InferResponse,
	mrlDimension int,
	inferElapsed time.Duration,
	requestStart time.Time,
) models.SearchAPIResponse {
	data := make([]models.EnrichedResult, len(infer.Data))
	for i, item := range infer.Data {
		data[i] = models.EnrichedResult{
			VectorID:         item.VectorID,
			CatalogProductID: item.CatalogProductID,
			SimilarityScore:  item.SimilarityScore,
			Caption:          item.Caption,
			// Keep the indexed filename for the native FashionGen image route.
			ProductID: item.ProductID,
		}
	}

	inferElapsedMs := inferElapsed.Seconds() * 1000.0
	httpOverheadMs := inferElapsedMs - infer.Timing.WorkerTotalMs
	if httpOverheadMs < 0 {
		httpOverheadMs = 0
	}

	var stage2Dim *int
	if infer.SearchConfig.Stage2Dim != nil {
		val := *infer.SearchConfig.Stage2Dim
		stage2Dim = &val
	}

	return models.SearchAPIResponse{
		Status:       "success",
		IndexVersion: infer.IndexVersion,
		MRLDimension: mrlDimension,
		Data:         data,
		SearchConfig: models.SearchConfigResp{
			RequestedDim: infer.SearchConfig.RequestedDim,
			SearchMode:   infer.SearchConfig.SearchMode,
			Stage1Dim:    infer.SearchConfig.Stage1Dim,
			Stage2Dim:    stage2Dim,
			AQEEnabled:   infer.SearchConfig.AQEEnabled,
		},
		Timing: models.SearchTimingResp{
			EncodeMs:       infer.Timing.EncodeMs,
			AQEMs:          infer.Timing.AQEMs,
			Stage1Ms:       infer.Timing.Stage1Ms,
			RerankMs:       infer.Timing.RerankMs,
			WorkerTotalMs:  infer.Timing.WorkerTotalMs,
			HTTPOverheadMs: roundMs(httpOverheadMs),
			EnrichMs:       0,
			RequestTotalMs: roundMs(time.Since(requestStart).Seconds() * 1000.0),
		},
	}
}

func roundMs(val float64) float64 {
	return float64(int(val*100+0.5)) / 100
}
