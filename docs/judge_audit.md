# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5` (backend replay, judge verdict lưu sẵn trong CSV; FAIL = lớp dương).

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok (`judge_tone_public.csv`) | 100 | 0.757 | 0.857 | 0.800 | **Đạt** (exit 0) | **dùng**, chỉ cho giọng điệu, không chặn release |
| helpful (`judge_helpful_public.csv`) | 100 | 0.375 | 1.000 | **0.300** | **Không** (κ, R dưới sàn; exit 1) | **loại** |

Ma trận nhầm lẫn:
- tone_ok: tp=24, fp=4, fn=6, tn=66. Tỉ lệ FAIL quan sát 0.28, sau Rogan-Gladen hiệu chỉnh còn **0.30**.
- helpful: tp=9, fp=0, fn=21, tn=70. Tỉ lệ FAIL quan sát 0.09, sau hiệu chỉnh là **0.30**. Judge báo thiếu hơn 3 lần so với tỉ lệ lỗi thật.

## ≥5 case audit thủ công
| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha, anh check giúp em." | PASS | FAIL | Người | Xưng "em" và dùng "nha" là quá suồng sã với khách khiếu nại. Judge hiểu nhầm thành "thân thiện". |
| 2 | H-029 "Dạ, vui lòng chờ… không cần nhắn thêm." | PASS | FAIL | Người | Giọng ra lệnh. Judge chỉ bám vào chữ "Dạ, vui lòng" ở đầu câu. |
| 3 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Câu ngắn nhưng đủ ý. Judge phạt vì "thiếu xin lỗi", tức áp một rubric không có trong guideline. |
| 4 | H-051 "Dạ, LogiX đã refund 90.000đ cho đơn O-202 ạ." | FAIL | PASS | Người | Guideline CS của LogiX cho phép dùng chữ "refund". Judge phạt tiếng Anh. |
| 5 | H-063 "…đã hoàn 20.000đ và sẽ hoàn thêm cho anh/chị ạ." | PASS | FAIL | Người | Câu hứa hẹn vượt kết quả hệ thống. Đây là lỗi nội dung, không phải giọng điệu. Grader code `reply_matches_ledger` mới là thứ cần bắt lỗi này. |
| 6 | H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn…" | FAIL | PASS | **Judge** | Nhãn người sai vì đọc nhầm ticket. Cần sửa nhãn trong lần gán nhãn tới. Lỗi nhãn này kéo P xuống nhẹ. |
| 7 | H-094 "Da, LogiX da hoan 40.000đ… xin loi…" | PASS | FAIL | Người | Câu mất dấu tiếng Việt kiểu dịch máy. Judge không nhạy với lỗi này. |
| 8 | HL-015 "Dạ, LogiX đã hoàn 55.000đ cho đơn O-112 ạ." (helpful) | PASS | FAIL | Người | Reply nói **sai tiền**: ledger chỉ ghi 40.000đ. Judge không thấy ledger nên không thể biết. |
| 9 | HL-043 reply dài, xin lỗi lặp lại, "đã hoàn 35.000đ" (helpful) | PASS | FAIL | Người | Reply sai tiền (ledger 20.000đ). Câu xin lỗi dài làm judge chấm PASS: judge thiên vị câu dài. |

## Kết luận
- **helpful bị loại.** Recall 0.30 nghĩa là judge bỏ sót 21/30 reply hỏng (fn=21). Trong 21 case bị sót, **18 case** có `human_failure = sai tiền` (3 case còn lại là "sai xưng hô"): đây là FM-08, mà judge không thể chấm đúng vì không đọc ledger. Theo quy tắc, tiền luôn chấm bằng code, nên FM-08 được thay bằng grader code `reply_matches_ledger` (blocking, min 0.95).
- **tone_ok được dùng** làm tín hiệu theo dõi, không nằm trong gate: cả 4 FP đều đi theo một kiểu (judge áp rubric "phải xin lỗi" / "cấm tiếng Anh"). Tỉ lệ lỗi giọng điệu báo cáo phải là số đã hiệu chỉnh Rogan-Gladen (0.30), không phải số quan sát.
- Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai, cần nhãn người mới để có held-out thật. Ít nhất 1 nhãn người sai (H-081), nên cần gán nhãn lại bởi người thứ hai. n=100, nên khoảng tin cậy của κ còn rộng.
