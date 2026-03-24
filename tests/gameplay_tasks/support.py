from __future__ import annotations


class Chain:
    def __init__(self, *, first_result=None, slice_result=None):
        self._first_result = first_result
        self._slice_result = slice_result or []

    def select_related(self, *args, **kwargs):
        return self

    def prefetch_related(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self._first_result

    def __getitem__(self, item):
        if isinstance(item, slice):
            return list(self._slice_result)
        raise TypeError("Only slicing is supported")


def patch_model(monkeypatch, dotted_path: str, *, first_result=None, slice_result=None, status_cls=None) -> None:
    attrs = {"objects": Chain(first_result=first_result, slice_result=slice_result)}
    if status_cls is not None:
        attrs["Status"] = status_cls
    dummy_cls = type("_DummyModel", (), attrs)
    monkeypatch.setattr(dotted_path, dummy_cls)
