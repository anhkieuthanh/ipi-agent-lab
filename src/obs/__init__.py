"""Tầng đo lường: trace store (STT-32), chi phí (STT-15), canary (STT-33, STT-34).

DDL sinh từ model SQLModel trong `trace.py`; bản ghi ra `schema.sql` để soát, test giữ hai bản
đồng bộ. `blocked_by ∈ {defense, model_refusal, harness}` là trường bắt buộc.
"""
