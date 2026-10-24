class _Traza(dict):
    def __init__(self, *a, **k):
        super().__init__(k)


Bar = Scatter = _Traza


class Figure:
    def __init__(self, data=None, **k):
        self.data = [data] if data else []

    def add_trace(self, t, **k):
        self.data.append(t)

    def update_layout(self, *a, **k):
        return self

    def update_yaxes(self, *a, **k):
        return self

    def add_vline(self, *a, **k):
        return self
