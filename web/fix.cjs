const fs = require('fs');
let c = fs.readFileSync('src/app/accounts/page.tsx', 'utf8');

c = c.replace(/\{t\(\"allStatus\"\)\}/g, '\"Tất cả trạng thái\"');
c = c.replace(/\{t\(\"active\"\)\}/g, '\"Hoạt động\"');
c = c.replace(/\{t\(\"limited\"\)\}/g, '\"Bị giới hạn\"');
c = c.replace(/\{t\(\"abnormal\"\)\}/g, '\"Bị lỗi\"');
c = c.replace(/\{t\(\"disabled\"\)\}/g, '\"Đã vô hiệu\"');
c = c.replace(/\{t\(\"quotaRemaining\"\)\}/g, '\"Hạn mức còn lại\"');
c = c.replace(/\{t\(\"totalAccounts\"\)\}/g, '\"Tổng tài khoản\"');

fs.writeFileSync('src/app/accounts/page.tsx', c, 'utf8');
