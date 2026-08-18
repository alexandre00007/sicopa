from __future__ import annotations


def configure_low_memory_export(con, threads: int = 2) -> None:
    """Réduit la pression mémoire des requêtes d'export DuckDB volumineuses."""
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET threads={max(1, min(int(threads or 1), 2))}")


def prepare_fusion_export_tables(con, fusion_id: str) -> dict:
    """Matérialise une base étroite et les stats d'identité une seule fois.

    Les anciennes requêtes utilisaient p.* + plusieurs CTE + ORDER BY global pour chaque
    feuille Excel. Sur plusieurs millions de lignes, DuckDB pouvait consommer toute la
    limite mémoire avant même le premier fetchmany(). Ces tables temporaires réduisent
    fortement la largeur des données et sont réutilisées par toutes les feuilles.
    """
    info = con.execute(
        "SELECT trimestre,annee FROM fusions_raw WHERE fusion_id=?", [fusion_id]
    ).fetchone()
    if not info:
        raise ValueError(f"Fusion introuvable : {fusion_id}")
    quarter, year = info[0], int(info[1])

    con.execute("DROP TABLE IF EXISTS tmp_sicorpa_fusion_export_base")
    con.execute("DROP TABLE IF EXISTS tmp_sicorpa_fusion_export_stats")
    con.execute("DROP TABLE IF EXISTS tmp_sicorpa_fusion_export_src")

    con.execute("""CREATE TEMP TABLE tmp_sicorpa_fusion_export_src AS
        SELECT execution_id,MIN(table_source) AS table_source
        FROM sources_fusion_raw
        WHERE fusion_id=? AND execution_id IS NOT NULL
        GROUP BY execution_id""", [fusion_id])

    con.execute("""CREATE TEMP TABLE tmp_sicorpa_fusion_export_base AS
        SELECT
            p.execution_id,p.ligne_paie_id,p.ligne_source,p.regime,p.institution_id,
            p.trimestre,p.annee,p.table_source,p.matricule_source,p.matricule_normalise,
            p.nom,p.prenom,p.nom_normalise,p.section,p.categorie,p.grade,
            p.unite_affectation,p.province,p.remuneration_brute_calculee,p.montant_net,
            CASE
                WHEN COALESCE(p.matricule_normalise,'') NOT IN ('','NU')
                    THEN 'M:'||p.matricule_normalise
                WHEN COALESCE(p.nom_normalise,'')<>''
                    THEN 'N:'||p.nom_normalise
                ELSE 'L:'||p.ligne_paie_id
            END AS person_key
        FROM paie_standardisee p
        JOIN tmp_sicorpa_fusion_export_src s ON s.execution_id=p.execution_id
        WHERE p.trimestre=? AND p.annee=?""", [quarter, year])

    con.execute("""CREATE TEMP TABLE tmp_sicorpa_fusion_export_stats AS
        SELECT person_key,
               COUNT(DISTINCT execution_id) AS nb_executions,
               COUNT(DISTINCT COALESCE(table_source,'')) AS nb_tables,
               STRING_AGG(DISTINCT NULLIF(nom_normalise,''),' | ') AS noms_distincts,
               STRING_AGG(DISTINCT NULLIF(matricule_normalise,''),' | ') AS matricules_distincts
        FROM tmp_sicorpa_fusion_export_base
        GROUP BY person_key""")

    # Les index évitent de reconstruire de gros hash tables pour chaque feuille de l'annexe 12.
    try:
        con.execute("CREATE INDEX idx_tmp_fusion_export_base_person ON tmp_sicorpa_fusion_export_base(person_key)")
        con.execute("CREATE INDEX idx_tmp_fusion_export_stats_person ON tmp_sicorpa_fusion_export_stats(person_key)")
    except Exception:
        # DuckDB peut choisir de ne pas créer un index temporaire selon la version ; l'export reste valide.
        pass

    row = con.execute("""SELECT COUNT(*),
        COALESCE(SUM(remuneration_brute_calculee),0),COALESCE(SUM(montant_net),0)
        FROM tmp_sicorpa_fusion_export_base""").fetchone()
    return {
        "quarter": quarter,
        "year": year,
        "physical_rows": int(row[0] or 0),
        "physical_gross": float(row[1] or 0),
        "physical_net": float(row[2] or 0),
    }


def cleanup_fusion_export_tables(con) -> None:
    for table in (
        "tmp_sicorpa_fusion_export_stats",
        "tmp_sicorpa_fusion_export_base",
        "tmp_sicorpa_fusion_export_src",
    ):
        try:
            con.execute(f"DROP TABLE IF EXISTS {table}")
        except Exception:
            pass
