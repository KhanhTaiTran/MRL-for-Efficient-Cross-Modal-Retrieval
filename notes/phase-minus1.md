# Phase -1: ổn định tìm kiếm và chuẩn bị nền tảng web

Commit chốt: `635226a` trên nhánh `dev`. Ngày: 29/10/2026.

## Mục tiêu

Làm luồng Next.js -> Go -> Python trả đúng sản phẩm, dùng đúng model/index và có thể kiểm chứng trước khi thêm database nghiệp vụ, auth và checkout.

## 1. Search chuyển từ RabbitMQ RPC sang HTTP

Trước đây Go publish request rồi chờ response trên callback queue chung. Các handler đồng thời có thể lấy nhầm response rồi bỏ nó; vòng chờ không thoát theo deadline. Search vẫn phải chờ kết quả nên queue không tạo ra trải nghiệm bất đồng bộ.

Hiện tại Go gọi FastAPI qua HTTP với context/timeout. RabbitMQ chỉ dành cho job nền ở phase sau. Source chính: `ai-worker/ai_worker/api/server.py`, `core-api/internal/broker/infer_client.go`, `internal/api/search_handler.go`, `internal/models/search.go`.

- `/infer/search/text`, `/infer/search/image`, `/infer/config`, `/infer/health` ở Python.
- `/api/search/text`, `/api/search/image`, `/api/search/config` ở Go.
- Upstream validation giữ status 400; upstream timeout trả 504.
- Semaphore giới hạn inference đồng thời. Model/index nạp một lần và giữ trong RAM.
- HTTP timeout dừng gateway chờ; không cưỡng bức dừng phép tính PyTorch đang chạy trong executor.

## 2. Hai chế độ retrieval có contract rõ

`direct`: cắt embedding ở dimension được chọn rồi L2-normalize và tìm FAISS; không AQE/rerank.

`adaptive`: shortlist 64D, rerank 512D; text có AQE, image không AQE. Response trả search_config thực thi, không chỉ echo lựa chọn người dùng. 8D không đưa vào supported dimensions vì không có trong loss training hiện tại.

Timing tách encode, AQE, stage-1, rerank, worker total và thời gian request phía gateway. CUDA encode được synchronize trước khi chốt timer. AQE hiện quét toàn bộ vector đầy đủ nên không được dùng timing stage-1 riêng để suy ra tốc độ toàn hệ thống.

## 3. Thay database retrieval sang FashionGen

Index cũ có 21.783 ảnh và tương ứng checkpoint mrl_clip_epoch_3.pt. Metadata từng trỏ nhầm sang FashionGen: ảnh mẫu có cosine 1.0 với model cũ, khoảng -0.0017 với FashionGen. Việc một sản phẩm không nằm trong top 10 tự nó không đủ chứng minh mismatch; phải so ảnh thực sự thuộc index và vector tương ứng.

Đã thay active database bằng toàn bộ FashionGen validation:

- 32.528 image/text vectors; 7.519 product IDs.
- CLIP ViT-B/16; checkpoint mrl_fashiongen_latest.pt.
- Cached image/text embeddings được kiểm tra với CSV/product IDs và fresh encoding ở 5 vị trí, cosine > 0.99999.
- Checkpoint best không khớp cache này nên không được chọn thay latest.
- Builder: `ai-worker/scripts/indexing/build_fashiongen_index.py`.
- Artifacts: image/text FAISS, image_paths, captions, product_ids, products snapshot và index_meta.
- Manifest lưu hash checkpoint, index, mapping và provenance. Worker từ chối metadata/model không hợp lệ.
- Database cũ giữ trong vector_db.backup-20261028T181959Z để rollback.

`catalog_product_id` là product ID FashionGen; `product_id` tạm vẫn là tên ảnh để tương thích image URL/Find Similar. UUID catalog và mapping theo version được chuẩn bị ở Phase 0.

## 4. Storefront và trang thử nghiệm tách vai trò

Storefront tiếng Anh: bỏ dropdown retrieval, slider dimension, score và latency. Chỉ hiển thị kết quả, tên ngắn, brand, giá và review nếu có dữ liệu. Không tạo giá/số sao giả từ similarity. FashionGen không có giá/review nên hiện Price unavailable / No reviews yet.

`/image-search` giữ vai trò công cụ thử nghiệm: direct mode theo từng dimension, đọc timing mới, không dùng để mô tả trải nghiệm người mua.

## 5. Kiểm chứng đã hoàn tất

- Go regression: validation, timeout 504, tên ảnh và concurrent requests.
- Python regression: direct ở 6 dimension, adaptive/AQE, image search, invalid input, concurrency, hash/config mismatch.
- Live Go -> Python: 10 request đồng thời, tải ảnh thật, Find Similar hai mode, self-match cosine > 0.999.
- 3 caption thật ở đầu/giữa/cuối FashionGen val đều tìm thấy đúng product ID trong top 10; đây là spot check, không phải Recall@10 toàn dataset.
- TypeScript và production build frontend pass; storefront được kiểm tra browser desktop/mobile.

Lệnh chạy lại: `.venv/Scripts/python.exe ai-worker/manage.py test --e2e`. Launcher local: `.venv/Scripts/python.exe ai-worker/manage.py start-local`.

## 6. Git và phần chưa thuộc Phase -1

Source được commit; generated index/metadata, checkpoint, cache, binary và secrets giữ ngoài Git. Các notebook/baseline cũ chưa bị xoá trong cleanup audit. Hai tài liệu HOW_TO_PROVE_MRL.md và MRL_Comparision.md đã bị xoá trước lượt commit và được ghi nhận cùng snapshot.

Chưa có SQL catalog/auth/orders, chưa có RabbitMQ indexing jobs, chưa có hot-swap index khi serving. Benchmark chất lượng MRL toàn dataset tách khỏi functional tests. Docker Compose cũ còn đường dẫn dataset cũ; đây là việc Phase 0 phải giải quyết.

## 7. Bàn giao Phase 0

Đưa PostgreSQL, S3-compatible storage, mail local và migrations vào Compose. Migration one-shot chạy trước seed; seed tạo catalog và index demo nhất quán; inference khởi động sau khi seed thành công. Tách liveness/readiness để không tạo vòng phụ thuộc index chưa tồn tại. Model và index lưu volume bền vững; nguồn FashionGen/checkpoint thật là cấu hình local riêng, không yêu cầu tài khoản dịch vụ cho demo.
