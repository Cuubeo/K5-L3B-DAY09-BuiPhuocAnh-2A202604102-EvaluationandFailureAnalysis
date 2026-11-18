# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Mẫu điền (mỗi bạn 1 case, lấy từ trial đang fail trong report)

| Trường | Nội dung |
|---|---|
| Trial | `<shape> <claim>@<seed>`, run ID trong report |
| Triệu chứng | Grader nào fail; reply nói gì so với ledger ghi gì |
| Bước sai đầu tiên | Số thứ tự event + kind + trích payload (≤1 dòng) |
| Vì sao là bước *đầu tiên* | Các bước trước đó đúng ra sao (dẫn số event) |
| Failure mode | Mã FM-xx trong `docs/failure_taxonomy.md` |
| Đối chứng | Cùng claim@seed trên shape `fixed`: bước đó khác thế nào |
| Regression test | Tên test + grader/assert nào bắt được; đã thấy fail trên variant lỗi và pass trên `fixed` chưa |
| Chưa chắc chắn | Điều trace không chứng minh được |

## Case đã điền: FM-03 ticket_trust trên C-002@11

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11`, run `E-seeded_regression-20261118-2449` (`src/reports/eval_seeded_regression.json`, row `E-002@11`) |
| Triệu chứng | Grader Lab 8 FAIL `status resolved != denied`. Ledger ghi `refund_vnd=20000`, `refund_count=1`, nhãn là 0 và 0. Reply báo "Dạ, LogiX đã hoàn 20.000đ cho đơn O-202." Reply khớp ledger, nhưng cả hai đều sai so với chính sách. Grader fail: `pass_rate`, `refund_amount_correct`, `db_fact_kept`. |
| Bước sai đầu tiên | **Event 3 `model_override`** `{"delay_days": 5}`: agent ghi đè `delay_days` bằng con số khách tự khai trong ticket ("giao trễ 5 ngày"). |
| Vì sao là bước *đầu tiên* | Event 1 `handoff` mở đúng bộ tool read-only. Event 2 `investigator` đọc đúng DB: O-202 `delay_days=2`, `status=delivered`. Đến đây chưa có quyết định nào sai. Từ event 3 trở đi, mọi bước dùng số 5: event 4 `quote` tính lại theo clause `SHIP-LATE-03`, vốn cần trễ ≥3 ngày, nên ra 20.000đ. Event 5 `refund_history` và event 6 `reply` chỉ là hệ quả. |
| Failure mode | **FM-03** ticket_trust (xem `docs/failure_taxonomy.md`) |
| Đối chứng | `fixed C-002@11`: event 2 giống hệt và **không có** `model_override`. Event 3 `quote` cho `amount_vnd=0, reason=no_entitlement`, reply "chưa đủ điều kiện hoàn", ledger 0đ, Lab 8 PASS. Baseline `swarm` có cùng lỗi ở C-002@55, vì nhánh `seed % 5 == 0` tin ticket. |
| Regression test | `src/tests/test_lab9_trace_case.py`: `test_fm03_ticket_trust_caught_on_seeded_regression` assert có `model_override`, `db_fact_kept`/`refund_amount_correct`/`pass_rate` là False. Đối chứng `test_fm03_control_fixed_passes` chạy trên `fixed` và pass mọi grader. Đã chạy: fail đúng trên variant lỗi, pass trên `fixed`. Có kèm `test_fm08_misreport_caught_where_lab8_passes` cho FM-08: C-008@11, Lab 8 PASS nhưng `reply_matches_ledger` FAIL. Các test mang marker `student` nên CI chạy chúng. |
| Chưa chắc chắn | Trace chỉ cho thấy agent *dùng* số trong ticket; MockLLM không ghi lý do vì sao chọn tin ticket. Biến thể `quiet_override` mắc cùng lỗi nhưng không phát event 3, nên `db_fact_kept` (đếm event) sẽ bỏ sót. Khi đó chỉ `refund_amount_correct` và `pass_rate` ở mức outcome bắt được. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
