# OAuth cho External MCP

Yêu cầu: quản trị viên có thể thêm MCP dùng OAuth, đăng nhập ở nhà cung cấp,
lưu token mã hóa, tự refresh, kiểm tra công cụ, đổi tài khoản và ngắt kết nối.
Các kết nối không xác thực/API key/headers hiện có tiếp tục hoạt động.

Trong **MCP → External MCP**, nhập URL và tên, chọn **OAuth**, rồi **Kết nối OAuth**.
Cửa sổ nhà cung cấp yêu cầu đăng nhập và cấp quyền. Sau callback, trang tự cập nhật
trạng thái. Bấm **Kiểm tra** để thực hiện bắt tay MCP và lấy danh sách công cụ.
Các công cụ của kết nối được bật sẽ được đưa vào luồng gọi MCP của gateway.

OAuth dùng Streamable HTTP với endpoint HTTPS công khai. Hỗ trợ discovery
Protected Resource Metadata, OAuth/OIDC issuer metadata, PKCE S256, Client ID
Metadata Documents (CIMD), Dynamic Client Registration và client đăng ký trước.
Nếu nhà cung cấp không cho tự đăng ký, mở cấu hình nâng cao để nhập Client ID,
Client Secret và scope theo ứng dụng đã đăng ký. Một số dịch vụ cần thuê bao hoặc
nhà cung cấp duyệt ứng dụng; khả năng OAuth không thay thế những điều kiện này.

## Cấu hình triển khai

Đặt `MCP_OAUTH_PUBLIC_URL=https://ai.example.com` thành origin của **API gateway**.
Callback đăng ký tại nhà cung cấp là
`https://ai.example.com/api/mcp/oauth/callback`.
Tài liệu CIMD công khai tại `/api/mcp/oauth/client-metadata`; chỉ bật khi đã cấu hình
origin HTTPS cố định. Reverse proxy phải chuyển tiếp hai đường dẫn này.
Không ghi query của callback vào access log vì nó chứa mã đăng nhập một lần.

Nếu không đặt biến origin, callback dùng origin request (HTTPS, hoặc HTTP localhost
cho phát triển); CIMD không bật. Trình duyệt phải truy cập API bằng cùng hostname
với callback để cookie liên kết phiên hoạt động. Khi frontend khác origin, cần
CORS có credentials và chính sách cookie của trình duyệt cho phép cookie API.

Token, refresh token, Client Secret và PKCE verifier chỉ lưu trong SQLite mã hóa
Fernet tại `DATA_DIR/mcp_oauth/`, không nằm trong `config.json` hoặc JSON trả cho UI.
Khóa tự sinh ở `mcp_oauth/key`, hoặc cung cấp qua `MCP_OAUTH_ENCRYPTION_KEY`.
Sao lưu thư mục cùng khóa an toàn; mất khóa sẽ không giải mã được phiên cũ.
Thư mục quyền 0700, key/database quyền 0600, được loại khỏi Git mặc định.
Mọi worker trên cùng máy phải dùng chung thư mục và khóa để serialize việc xoay
refresh token. Không hỗ trợ nhiều replica với các ổ đĩa OAuth độc lập; cần volume
SQLite có khóa filesystem tin cậy dùng chung hoặc chỉ chạy một replica.

Phiên đăng nhập hết hạn sau 10 phút, state dùng một lần và gắn với cookie HttpOnly.
Metadata và token endpoint được kiểm tra HTTPS/IP công khai, không tự theo redirect.
Token chỉ gửi tới đúng URL MCP đã liên kết. Khi hết hạn, gateway tự refresh nếu có
refresh token; khi bị 401, thử refresh rồi gửi lại đúng một lần. Nếu vẫn bị từ chối
hoặc refresh token mất hiệu lực, UI yêu cầu đăng nhập lại. Không tự phát lại tool
do timeout hoặc lỗi mạng chung.

**Ngắt kết nối** xóa token cục bộ ngay, hủy callback đang chờ và thử thu hồi token
tại nhà cung cấp nếu có endpoint revocation. Nếu revocation thất bại hoặc không
được hỗ trợ, có thể thu hồi quyền thêm trong phần ứng dụng liên kết của nhà cung cấp.
Xóa MCP và thay kết nối OAuth bằng API key cũng hủy phiên OAuth cũ.
Ngắt kết nối giữ đăng ký client trong kho mã hóa để lần kết nối lại chỉ cần đăng
nhập nhà cung cấp; xóa MCP sẽ xóa cả Client ID/Secret của kết nối đó.

## Kiểm chứng

`python -m pytest test/test_mcp_oauth.py test/test_mcp_oauth_api.py test/test_mcp_oauth_client.py test/test_mcp_api.py test/test_mcp_client.py`

Các test dùng nhà cung cấp giả để kiểm tra vòng đời đầy đủ, CSRF/state/PKCE,
refresh đồng thời, từ chối token và không tiết lộ credential. Đăng nhập với dịch vụ
thực vẫn cần chủ tài khoản tự cấp quyền trong trình duyệt.

Tham chiếu: [MCP Authorization 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization).

Kiểm tra metadata trực tiếp ngày 08/09/2026 (chưa đăng ký client hoặc đăng nhập):

| Endpoint | Kết quả discovery |
| --- | --- |
| Stripe, Consensus, DeepL, Smartling, MT Newswires, CoinDesk, Kick, Meridian | Qua discovery; quảng bá tự đăng ký client |
| Spotify, Clear Street | Qua discovery; cần Client ID đăng ký trước |
| QuickBooks | Metadata bị từ chối HTTP 403 từ môi trường thử |
| Xero, LILT, Embat | Issuer trong protected-resource metadata có dấu `/` cuối, khác issuer trong tài liệu authorization; bị từ chối theo kiểm tra issuer chính xác |

Resource có thể là origin hoặc đường dẫn cha cùng origin mà nhà cung cấp công bố
(ví dụ Consensus/Spotify), còn token gửi đi vẫn bị ràng buộc với URL MCP cấu hình
chính xác. Không chấp nhận audience ở origin, port hoặc nhánh đường dẫn khác.

Kiểm chứng local: 36 test MCP đạt; build Next.js và TypeScript đạt; Chrome desktop
và mobile chạy qua đăng nhập giả lập, callback, discovery công cụ, ngắt kết nối,
kết nối lại và xóa. Lượt full suite có 5.360 passed, 85 skipped, 564 subtests passed;
17 test HTTP cần gateway thật ở localhost:8000 bị connection refused. Máy Intel
macOS local dùng cryptography 48.0.1 để kiểm thử vì chưa có wheel tương thích của
50.x; yêu cầu dependency dự án vẫn giữ nguyên >=50.0.0.
