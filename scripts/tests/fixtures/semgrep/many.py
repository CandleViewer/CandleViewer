"""Fixture for #3549: too many matches, so Semgrep drops every finding here."""


def g(value: int) -> int:
    return value


v0 = g(0)
v1 = g(1)
v2 = g(2)
v3 = g(3)
v4 = g(4)
v5 = g(5)
v6 = g(6)
v7 = g(7)
v8 = g(8)
v9 = g(9)
v10 = g(10)
v11 = g(11)
v12 = g(12)
v13 = g(13)
v14 = g(14)
v15 = g(15)
v16 = g(16)
v17 = g(17)
v18 = g(18)
v19 = g(19)
print(v0)
