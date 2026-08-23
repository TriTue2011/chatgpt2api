# n8n MCP, ChatGPT và mức tương thích của ChatGPT2API

Tài liệu này phân biệt hai cách dùng dễ bị gọi chung là “thêm n8n MCP”:

1. **ChatGPT chính chủ kết nối thẳng n8n** qua Apps/Developer mode.
2. **ChatGPT2API kết nối n8n hoặc MCP khác** để đưa các tool vào lượt chat của gateway này.

## Ba vai trò MCP khác nhau trong n8n

| Trường hợp | n8n đóng vai trò | Endpoint/cách dùng |
|---|---|---|
| MCP cấp instance | MCP server | `https://<n8n>/mcp-server/http`; chỉ workflow đã bật quyền MCP mới xuất hiện |
| MCP Server Trigger | MCP server của một workflow | Dùng **Production URL** trên node; hỗ trợ Streamable HTTP và SSE |
| MCP Client / MCP Client Tool | MCP client | n8n gọi một MCP bên ngoài; không phải URL để ChatGPT2API kết nối vào n8n |

Nguồn n8n: [instance-level MCP](https://docs.n8n.io/connect/connect-to-n8n-mcp-server/), [MCP Server Trigger](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-langchain.mcptrigger/), [MCP Client Tool](https://docs.n8n.io/integrations/builtin/cluster-nodes/sub-nodes/n8n-nodes-langchain.toolmcp/), [MCP credentials](https://docs.n8n.io/integrations/builtin/credentials/mcp/).

## Thêm n8n vào ChatGPT2API

Trong dashboard, mở **MCP Servers & Studio → External MCP**:

1. Dán endpoint cấp instance hoặc Production URL của MCP Server Trigger.
2. Để transport là **Tự nhận dạng**.
3. Nếu n8n dùng API key/Bearer, dán token vào ô Bearer. Nếu dùng Header Auth, nhập JSON, ví dụ `{"X-API-Key":"..."}`.
4. Bấm **Kiểm tra**. Chỉ thêm server sau khi thấy phiên bản giao thức và số tool.

Client trong gateway hiện hỗ trợ:

- MCP `2026-07-28` stateless (`server/discover`, `_meta`, `Mcp-Method`, `Mcp-Name`, `Mcp-Param-*`);
- các phiên bản session/initialize `2025-11-25`, `2025-06-18`, `2025-03-26`, `2024-11-05`;
- Streamable HTTP trả JSON hoặc request-scoped SSE;
- HTTP+SSE cũ, cả chọn trực tiếp lẫn tự fallback;
- Bearer và nhiều custom headers;
- phân trang `tools/list`, JSON Schema input, kết quả text/structured/non-text dạng JSON;
- nhiều MCP song song, kể cả tool trùng tên hoặc tên không hợp lệ với OpenAI (gateway tự tạo alias ổn định);
- chặn custom header thuộc quyền giao thức và chặn redirect mang credential sang origin khác;
- đọc dòng SSE tới đúng phản hồi rồi đóng, nên server giữ dòng mở hay chèn keep-alive vẫn trả kết quả ngay;
- nhận diện đời giao thức theo đúng luật fallback của spec: đọc thân phản hồi 400/404 trước khi tụt về `initialize`, nên server chỉ nói MCP 2026 (kể cả bản thiếu `server/discover`) vẫn dùng được;
- MRTR một vòng: server trả `input_required` kèm `requestState` thì gateway gửi lại ngay để hoàn tất lượt gọi;
- server chỉ có resources/prompts vẫn được coi là đang sống (không bị circuit breaker), chỉ là không có tool nào;
- lỗi `tools/call` được nói thẳng cho model (thiếu tham số, sai kiểu…) thay vì im lặng báo hỏng;
- `x-mcp-header` kể cả ở property lồng nhau; tool khai sai annotation bị loại khỏi danh sách đúng như spec yêu cầu.

## Kết nối trực tiếp trong ChatGPT

n8n hiện liệt kê ChatGPT là web client được hỗ trợ. Với ChatGPT, tạo custom app/MCP app, nhập remote endpoint và hoàn tất OAuth nếu n8n yêu cầu. Khả năng này phụ thuộc gói ChatGPT và quyền workspace; full MCP/write hiện dành cho Business và Enterprise/Edu, còn Pro bị giới hạn hơn. ChatGPT không kết nối trực tiếp MCP ở localhost/private network; trường hợp đó cần Secure MCP Tunnel.

Nguồn OpenAI: [Developer mode and MCP apps in ChatGPT](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt-beta).

## Giới hạn có chủ ý

- UI External MCP chỉ nhận **remote HTTP(S)**. Không nhận lệnh `stdio`, vì cho phép nhập một command tùy ý từ dashboard tương đương quyền thực thi mã trên máy chủ.
- OAuth động/DCR trong ChatGPT2API chưa có luồng đăng nhập và refresh token. Với n8n trong gateway này, dùng API key/Bearer hoặc Header Auth. Nếu cần OAuth đầy đủ, kết nối n8n trực tiếp từ ChatGPT hoặc đặt một gateway OAuth phía trước.
- Gateway tiêu thụ capability **tools**. MCP chỉ có resources/prompts mà không công bố tool sẽ kết nối được nhưng không tạo function cho model. Server cần bọc thao tác cần dùng thành tool.
- Sampling, elicitation, roots và các `inputRequests` khác của MRTR không được tự động chấp thuận. Gateway khai `clientCapabilities` rỗng nên server đúng chuẩn sẽ không hỏi; server nào vẫn hỏi thì lượt gọi trả về câu giải thích thay vì kết quả. Đây là ranh giới an toàn: một MCP ngoài không được quyền tự gọi model hay đòi xác nhận thao tác nhạy cảm mà không có policy/approval riêng.
- ChatGPT giữ snapshot tool đã được workspace phê duyệt; khi MCP thêm hay đổi tool, admin phải Refresh/republish trong ChatGPT. ChatGPT2API tự làm mới khi cấu hình server thay đổi và định kỳ làm mới cache.

Không client nào có thể bảo đảm “mọi MCP” nếu server dùng transport riêng, giao thức sai chuẩn hoặc một cơ chế auth độc quyền. Mục tiêu của triển khai này là tương thích các transport/version chuẩn đang tồn tại, fallback có kiểm soát và báo lỗi rõ khi gặp phần mở rộng chưa hỗ trợ.

