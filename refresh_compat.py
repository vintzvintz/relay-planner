"""
Lit compat_coureurs.xlsx et génère compat.py avec la matrice de compatibilité
et la fonction is_compatible().
"""

import openpyxl

XLSX_PATH = "compat_coureurs.xlsx"
OUTPUT_PATH = "compat.py"


def read_matrix(path: str) -> tuple[list[str], dict[tuple[str, str], bool]]:
    wb = openpyxl.load_workbook(path)
    ws = wb.active

    rows = list(ws.iter_rows(min_row=4, max_row=18, min_col=2, max_col=16, values_only=True))
    header = [c for c in rows[0][1:] if c is not None]
    n = len(header)

    compat: dict[tuple[str, str], int] = {}
    errors = []
    for data_row in rows[1:]:
        row_name = data_row[0]
        if row_name is None:
            continue
        for col_idx, col_name in enumerate(header):
            val = data_row[col_idx + 1]
            if row_name == col_name:
                continue  # diagonale, ignorée
            if val is None:
                val = 0
            elif isinstance(val, float) and val.is_integer():
                val = int(val)
            if not isinstance(val, int) or val < 0:
                errors.append(f"  ({row_name}, {col_name}): {val!r} n'est pas un entier naturel")
                continue
            compat[(row_name, col_name)] = val
            compat[(col_name, row_name)] = val

    if errors:
        raise ValueError("Valeurs invalides dans la matrice :\n" + "\n".join(errors))

    return header, compat


def generate_compat_py(runners: list[str], compat: dict[tuple[str, str], int]) -> str:
    lines = [
        '"""',
        "Matrice de compatibilité générée automatiquement par refresh_compat.py.",
        'Ne pas modifier manuellement — éditer compat_coureurs.xlsx puis relancer refresh_compat.py.',
        '"""',
        "",
        "# fmt: off",
        "COMPAT_MATRIX: dict[tuple[str, str], int] = {",
    ]

    for r1 in runners:
        for r2 in runners:
            if r1 == r2:
                continue
            val = compat.get((r1, r2), 0)
            lines.append(f'    ("{r1}", "{r2}"): {val},')

    lines += [
        "}",
        "# fmt: on",
    ]

    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    runners, compat = read_matrix(XLSX_PATH)
    content = generate_compat_py(runners, compat)
    with open(OUTPUT_PATH, "w") as f:
        f.write(content)
    print(f"Généré : {OUTPUT_PATH}  ({len(runners)} coureurs, {sum(v > 0 for v in compat.values()) // 2} paires compatibles)")
