package models

// SearchAPIResponse is returned to the frontend.
type SearchAPIResponse struct {
	Status       string           `json:"status"`
	IndexVersion string           `json:"index_version"`
	MRLDimension int              `json:"mrl_dimension"`
	Data         []EnrichedResult `json:"data"`
	SearchConfig SearchConfigResp `json:"search_config"`
	Timing       SearchTimingResp `json:"timing"`
}

// EnrichedResult represents an item in the search results.
// Catalog fields are enriched using the version returned by inference.
type EnrichedResult struct {
	CatalogProductID string   `json:"catalog_product_id,omitempty"`
	VectorID         int      `json:"vector_id"`
	SimilarityScore  float64  `json:"similarity_score"`
	Caption          string   `json:"caption"`
	ProductID        string   `json:"product_id,omitempty"`
	Handle           string   `json:"handle,omitempty"`
	Name             string   `json:"name,omitempty"`
	Price            *float64 `json:"price,omitempty"`
	Brand            string   `json:"brand,omitempty"`
	Currency         string   `json:"currency,omitempty"`
	RatingAverage    *float64 `json:"rating_average"`
	ReviewCount      int      `json:"review_count"`
	ImageURL         string   `json:"image_url,omitempty"`
}

// SearchConfigResp describes the actual search execution parameters.
type SearchConfigResp struct {
	RequestedDim int    `json:"requested_dim"`
	SearchMode   string `json:"search_mode"`
	Stage1Dim    int    `json:"stage1_dim"`
	Stage2Dim    *int   `json:"stage2_dim"`
	AQEEnabled   bool   `json:"aqe_enabled"`
}

// SearchTimingResp contains granular latency measurements to analyze MRL trade-offs.
type SearchTimingResp struct {
	EncodeMs       float64 `json:"encode_ms"`
	AQEMs          float64 `json:"aqe_ms"`
	Stage1Ms       float64 `json:"stage1_ms"`
	RerankMs       float64 `json:"rerank_ms"`
	WorkerTotalMs  float64 `json:"worker_total_ms"`
	HTTPOverheadMs float64 `json:"http_overhead_ms"`
	EnrichMs       float64 `json:"enrich_ms"`
	RequestTotalMs float64 `json:"request_total_ms"`
}
