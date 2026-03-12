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

    compat: dict[tuple[str, str], bool] = {}
    for data_row in rows[1:]:
        row_name = data_row[0]
        if row_name is None:
            continue
        for col_idx, col_name in enumerate(header):
            val = data_row[col_idx + 1]
            is_compat = val == "Oui"
            compat[(row_name, col_name)] = is_compat
            compat[(col_name, row_name)] = is_compat

    return header, compat


def generate_compat_py(runners: list[str], compat: dict[tuple[str, str], bool]) -> str:
    lines = [
        '"""',
        "Matrice de compatibilité générée automatiquement par refresh_compat.py.",
        'Ne pas modifier manuellement — éditer compat_coureurs.xlsx puis relancer refresh_compat.py.',
        '"""',
        "",
        "# fmt: off",
        "COMPAT_MATRIX: dict[tuple[str, str], bool] = {",
    ]

    for r1 in runners:
        for r2 in runners:
            if r1 == r2:
                continue
            val = compat.get((r1, r2), False)
            lines.append(f'    ("{r1}", "{r2}"): {val},')

    lines += [
        "}",
        "# fmt: on",
        "",
        "",
        "def is_compatible(coureur_1: str, coureur_2: str) -> bool:",
        '    """Retourne True si coureur_1 et coureur_2 peuvent former un binôme."""',
        "    return COMPAT_MATRIX.get((coureur_1, coureur_2), False)",
    ]

    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    runners, compat = read_matrix(XLSX_PATH)
    content = generate_compat_py(runners, compat)
    with open(OUTPUT_PATH, "w") as f:
        f.write(content)
    print(f"Généré : {OUTPUT_PATH}  ({len(runners)} coureurs, {sum(compat.values()) // 2} paires compatibles)")
