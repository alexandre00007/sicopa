from __future__ import annotations


class SqlTemplateLibrary:
    """Bibliothèque de modèles SQL DuckDB strictement orientés lecture."""

    TEMPLATES = {
        "Sélection — Toutes les colonnes": "SELECT *\nFROM {table_a}\nLIMIT 100;",
        "Sélection — Colonnes choisies": "SELECT\n    colonne_1,\n    colonne_2\nFROM {table_a}\nLIMIT 100;",
        "Sélection — DISTINCT": "SELECT DISTINCT colonne\nFROM {table_a}\nORDER BY colonne;",
        "Filtre — WHERE égalité": "SELECT *\nFROM {table_a}\nWHERE colonne = 'valeur'\nLIMIT 100;",
        "Filtre — Plusieurs conditions AND": "SELECT *\nFROM {table_a}\nWHERE condition_1\n  AND condition_2\nLIMIT 100;",
        "Filtre — Plusieurs conditions OR": "SELECT *\nFROM {table_a}\nWHERE condition_1\n   OR condition_2\nLIMIT 100;",
        "Filtre — BETWEEN": "SELECT *\nFROM {table_a}\nWHERE colonne BETWEEN valeur_min AND valeur_max\nLIMIT 100;",
        "Filtre — IN": "SELECT *\nFROM {table_a}\nWHERE colonne IN ('valeur_1', 'valeur_2')\nLIMIT 100;",
        "Filtre — LIKE / ILIKE": "SELECT *\nFROM {table_a}\nWHERE CAST(colonne AS VARCHAR) ILIKE '%texte%'\nLIMIT 100;",
        "Filtre — NULL / non NULL": "SELECT *\nFROM {table_a}\nWHERE colonne IS NULL;\n\n-- Variante : colonne IS NOT NULL",
        "Tri — ORDER BY": "SELECT *\nFROM {table_a}\nORDER BY colonne DESC\nLIMIT 100;",
        "Agrégation — COUNT": "SELECT COUNT(*) AS nombre_lignes\nFROM {table_a};",
        "Agrégation — COUNT DISTINCT": "SELECT COUNT(DISTINCT colonne) AS valeurs_distinctes\nFROM {table_a};",
        "Agrégation — SUM / AVG / MIN / MAX": "SELECT\n    SUM(colonne_montant) AS total,\n    AVG(colonne_montant) AS moyenne,\n    MIN(colonne_montant) AS minimum,\n    MAX(colonne_montant) AS maximum\nFROM {table_a};",
        "Agrégation — GROUP BY": "SELECT\n    colonne_groupe,\n    COUNT(*) AS nombre,\n    SUM(colonne_montant) AS total\nFROM {table_a}\nGROUP BY colonne_groupe\nORDER BY total DESC;",
        "Agrégation — GROUP BY + HAVING": "SELECT\n    colonne_groupe,\n    COUNT(*) AS nombre\nFROM {table_a}\nGROUP BY colonne_groupe\nHAVING COUNT(*) > 1\nORDER BY nombre DESC;",
        "JOIN — INNER JOIN": "SELECT a.*, b.*\nFROM {table_a} a\nINNER JOIN {table_b} b\n    ON a.cle = b.cle\nLIMIT 200;",
        "JOIN — LEFT JOIN": "SELECT a.*, b.*\nFROM {table_a} a\nLEFT JOIN {table_b} b\n    ON a.cle = b.cle\nLIMIT 200;",
        "JOIN — RIGHT JOIN": "SELECT a.*, b.*\nFROM {table_a} a\nRIGHT JOIN {table_b} b\n    ON a.cle = b.cle\nLIMIT 200;",
        "JOIN — FULL OUTER JOIN": "SELECT a.*, b.*\nFROM {table_a} a\nFULL OUTER JOIN {table_b} b\n    ON a.cle = b.cle\nLIMIT 200;",
        "JOIN — CROSS JOIN": "SELECT a.*, b.*\nFROM {table_a} a\nCROSS JOIN {table_b} b\nLIMIT 200;",
        "JOIN — Plusieurs clés": "SELECT a.*, b.*\nFROM {table_a} a\nINNER JOIN {table_b} b\n    ON a.cle_1 = b.cle_1\n   AND a.cle_2 = b.cle_2\nLIMIT 200;",
        "JOIN — Condition supplémentaire": "SELECT a.*, b.*\nFROM {table_a} a\nLEFT JOIN {table_b} b\n    ON a.cle = b.cle\n   AND b.colonne_statut = 'ACTIF'\nLIMIT 200;",
        "JOIN — Auto-jointure (self join)": "SELECT a.*, b.*\nFROM {table_a} a\nINNER JOIN {table_a} b\n    ON a.cle = b.cle\n   AND a.rowid <> b.rowid\nLIMIT 200;",
        "JOIN — Agrégation préalable": "WITH b_agrege AS (\n    SELECT cle, SUM(colonne_montant) AS total_b\n    FROM {table_b}\n    GROUP BY cle\n)\nSELECT a.*, b.total_b\nFROM {table_a} a\nLEFT JOIN b_agrege b ON a.cle = b.cle\nLIMIT 200;",
        "JOIN — EXISTS (semi-join)": "SELECT a.*\nFROM {table_a} a\nWHERE EXISTS (\n    SELECT 1\n    FROM {table_b} b\n    WHERE b.cle = a.cle\n)\nLIMIT 200;",
        "JOIN — NOT EXISTS (anti-join)": "SELECT a.*\nFROM {table_a} a\nWHERE NOT EXISTS (\n    SELECT 1\n    FROM {table_b} b\n    WHERE b.cle = a.cle\n)\nLIMIT 200;",
        "Comparaison — Présents dans A et B": "SELECT a.*\nFROM {table_a} a\nINNER JOIN {table_b} b ON a.matricule = b.matricule\nLIMIT 200;",
        "Comparaison — Présents dans A pas B": "SELECT a.*\nFROM {table_a} a\nWHERE NOT EXISTS (\n    SELECT 1 FROM {table_b} b\n    WHERE b.matricule = a.matricule\n)\nLIMIT 200;",
        "Comparaison — Présents dans B pas A": "SELECT b.*\nFROM {table_b} b\nWHERE NOT EXISTS (\n    SELECT 1 FROM {table_a} a\n    WHERE a.matricule = b.matricule\n)\nLIMIT 200;",
        "Comparaison — Même matricule, montant différent": "SELECT\n    a.matricule,\n    a.montant AS montant_a,\n    b.montant AS montant_b,\n    COALESCE(a.montant,0) - COALESCE(b.montant,0) AS ecart\nFROM {table_a} a\nINNER JOIN {table_b} b ON a.matricule = b.matricule\nWHERE COALESCE(a.montant,0) <> COALESCE(b.montant,0)\nORDER BY ABS(ecart) DESC;",
        "Comparaison — Même nom, matricule différent": "SELECT\n    a.nom, a.matricule AS matricule_a,\n    b.matricule AS matricule_b\nFROM {table_a} a\nINNER JOIN {table_b} b\n    ON UPPER(TRIM(a.nom)) = UPPER(TRIM(b.nom))\nWHERE COALESCE(CAST(a.matricule AS VARCHAR),'') <> COALESCE(CAST(b.matricule AS VARCHAR),'');",
        "Sous-requête — WHERE IN": "SELECT *\nFROM {table_a}\nWHERE cle IN (\n    SELECT cle FROM {table_b}\n)\nLIMIT 200;",
        "Sous-requête — FROM": "SELECT x.*\nFROM (\n    SELECT * FROM {table_a}\n    WHERE condition\n) x\nLIMIT 200;",
        "Sous-requête — Valeur scalaire": "SELECT\n    a.*,\n    (SELECT AVG(colonne_montant) FROM {table_a}) AS moyenne_globale\nFROM {table_a} a\nLIMIT 200;",
        "CTE — WITH simple": "WITH base AS (\n    SELECT * FROM {table_a}\n    WHERE condition\n)\nSELECT *\nFROM base\nLIMIT 200;",
        "CTE — Plusieurs CTE": "WITH a AS (\n    SELECT * FROM {table_a}\n),\nb AS (\n    SELECT * FROM {table_b}\n)\nSELECT a.*, b.*\nFROM a\nLEFT JOIN b ON a.cle = b.cle\nLIMIT 200;",
        "CTE — Agrégation + JOIN": "WITH totaux AS (\n    SELECT cle, SUM(colonne_montant) AS total\n    FROM {table_b}\n    GROUP BY cle\n)\nSELECT a.*, t.total\nFROM {table_a} a\nLEFT JOIN totaux t ON a.cle = t.cle\nLIMIT 200;",
        "Fenêtre — ROW_NUMBER": "SELECT\n    *,\n    ROW_NUMBER() OVER (PARTITION BY colonne_groupe ORDER BY colonne_tri DESC) AS rang\nFROM {table_a};",
        "Fenêtre — RANK / DENSE_RANK": "SELECT\n    *,\n    RANK() OVER (PARTITION BY colonne_groupe ORDER BY colonne_montant DESC) AS rang,\n    DENSE_RANK() OVER (PARTITION BY colonne_groupe ORDER BY colonne_montant DESC) AS rang_dense\nFROM {table_a};",
        "Fenêtre — SUM / AVG OVER": "SELECT\n    *,\n    SUM(colonne_montant) OVER (PARTITION BY colonne_groupe) AS total_groupe,\n    AVG(colonne_montant) OVER (PARTITION BY colonne_groupe) AS moyenne_groupe\nFROM {table_a};",
        "Fenêtre — LAG / LEAD": "SELECT\n    *,\n    LAG(colonne_montant) OVER (PARTITION BY matricule ORDER BY periode) AS montant_precedent,\n    LEAD(colonne_montant) OVER (PARTITION BY matricule ORDER BY periode) AS montant_suivant\nFROM {table_a};",
        "Transformation — CASE WHEN": "SELECT\n    *,\n    CASE\n        WHEN condition_1 THEN 'Catégorie 1'\n        WHEN condition_2 THEN 'Catégorie 2'\n        ELSE 'Autre'\n    END AS classification\nFROM {table_a}\nLIMIT 200;",
        "Transformation — COALESCE / NULLIF": "SELECT\n    COALESCE(colonne, 'Valeur par défaut') AS valeur,\n    NULLIF(colonne_2, '') AS valeur_nullifiee\nFROM {table_a}\nLIMIT 200;",
        "Transformation — CAST": "SELECT\n    CAST(colonne AS VARCHAR) AS texte,\n    TRY_CAST(colonne_montant AS DECIMAL(18,2)) AS montant\nFROM {table_a}\nLIMIT 200;",
        "Transformation — TRIM / UPPER / LOWER": "SELECT\n    TRIM(colonne) AS valeur_nettoyee,\n    UPPER(TRIM(colonne)) AS valeur_majuscule,\n    LOWER(TRIM(colonne)) AS valeur_minuscule\nFROM {table_a}\nLIMIT 200;",
        "Transformation — Calcul écart et pourcentage": "SELECT\n    valeur_a, valeur_b,\n    COALESCE(valeur_a,0) - COALESCE(valeur_b,0) AS ecart,\n    CASE WHEN GREATEST(ABS(COALESCE(valeur_a,0)), ABS(COALESCE(valeur_b,0))) = 0 THEN 0\n         ELSE 100.0 * ABS(COALESCE(valeur_a,0)-COALESCE(valeur_b,0)) /\n              GREATEST(ABS(COALESCE(valeur_a,0)), ABS(COALESCE(valeur_b,0))) END AS ecart_pct\nFROM {table_a};",
        "Qualité — Doublons par matricule": "SELECT\n    matricule,\n    COUNT(*) AS occurrences\nFROM {table_a}\nWHERE matricule IS NOT NULL\nGROUP BY matricule\nHAVING COUNT(*) > 1\nORDER BY occurrences DESC;",
        "Qualité — Doublons par nom": "SELECT\n    UPPER(TRIM(nom)) AS nom_normalise,\n    COUNT(*) AS occurrences\nFROM {table_a}\nWHERE COALESCE(TRIM(nom),'') <> ''\nGROUP BY UPPER(TRIM(nom))\nHAVING COUNT(*) > 1\nORDER BY occurrences DESC;",
        "Qualité — Valeurs NULL / vides": "SELECT\n    COUNT(*) AS total,\n    SUM(CASE WHEN colonne IS NULL THEN 1 ELSE 0 END) AS nulles,\n    SUM(CASE WHEN TRIM(CAST(colonne AS VARCHAR)) = '' THEN 1 ELSE 0 END) AS vides\nFROM {table_a};",
        "Qualité — Fréquences des valeurs": "SELECT\n    colonne,\n    COUNT(*) AS occurrences\nFROM {table_a}\nGROUP BY colonne\nORDER BY occurrences DESC\nLIMIT 100;",
        "Qualité — Statistiques numériques": "SELECT\n    COUNT(colonne_montant) AS n,\n    MIN(colonne_montant) AS minimum,\n    MAX(colonne_montant) AS maximum,\n    AVG(colonne_montant) AS moyenne,\n    MEDIAN(colonne_montant) AS mediane,\n    STDDEV_SAMP(colonne_montant) AS ecart_type\nFROM {table_a};",
        "Qualité — Matricules manquants": "SELECT *\nFROM {table_a}\nWHERE matricule IS NULL\n   OR TRIM(CAST(matricule AS VARCHAR)) = ''\n   OR UPPER(TRIM(CAST(matricule AS VARCHAR))) IN ('NU','N.U')\nLIMIT 500;",
        "Contrôle paie — Fictifs / identités suspectes": "-- Adaptez les noms de colonnes si la table RAW utilise d'autres libellés.\nSELECT *\nFROM {table_a}\nWHERE UPPER(COALESCE(CAST(matricule AS VARCHAR),'')) LIKE '%FICTIF%'\n   OR UPPER(COALESCE(CAST(nom AS VARCHAR),'')) LIKE '%FICTIF%'\n   OR UPPER(COALESCE(CAST(prenom AS VARCHAR),'')) LIKE '%FICTIF%'\n   OR UPPER(COALESCE(CAST(observation AS VARCHAR),'')) LIKE '%FICTIF%'\n   OR UPPER(COALESCE(CAST(nom AS VARCHAR),'')) IN ('TEST','INCONNU','ANONYME')\nLIMIT 500;",
        "Contrôle paie — Montants nuls ou négatifs": "SELECT *\nFROM {table_a}\nWHERE COALESCE(colonne_montant,0) <= 0\nLIMIT 500;",
        "Contrôle paie — Top rémunérations": "SELECT *\nFROM {table_a}\nORDER BY colonne_montant DESC\nLIMIT 100;",
    }

    @classmethod
    def names(cls) -> list[str]:
        return list(cls.TEMPLATES)

    @classmethod
    def render(cls, name: str, table_a: str, table_b: str | None = None) -> str:
        if name not in cls.TEMPLATES:
            raise ValueError("Modèle SQL inconnu.")
        if not table_a:
            raise ValueError("Sélectionnez d'abord une table RAW principale.")
        safe_a = '"' + str(table_a).replace('"', '""') + '"'
        safe_b = '"' + str(table_b or table_a).replace('"', '""') + '"'
        return cls.TEMPLATES[name].format(table_a=safe_a, table_b=safe_b)
