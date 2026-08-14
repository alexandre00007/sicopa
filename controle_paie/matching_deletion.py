from __future__ import annotations


class MatchingDeletionService:
    """Historique et suppression transactionnelle des exécutions de rapprochement."""

    def __init__(self, db):
        self.db = db

    def list_runs(self, limit: int = 200) -> list[tuple]:
        with self.db.connect() as con:
            return con.execute("""
                SELECT
                    r.execution_id,
                    COALESCE(i.nom_officiel, r.institution_id) AS institution,
                    r.institution_id,
                    r.regime,
                    r.trimestre,
                    r.annee,
                    COUNT(*) AS lignes,
                    SUM(CASE WHEN COALESCE(r.statut_validation,'A_VALIDER') <> 'A_VALIDER' THEN 1 ELSE 0 END) AS validees,
                    COALESCE(SUM(r.masse_financiere_controlee),0) AS masse,
                    COALESCE(SUM(r.impact_potentiel),0) AS impact_potentiel,
                    MAX(r.date_validation) AS derniere_validation
                FROM resultats_rapprochement r
                LEFT JOIN institutions i ON i.institution_id=r.institution_id
                WHERE COALESCE(r.execution_id,'') <> ''
                GROUP BY r.execution_id,i.nom_officiel,r.institution_id,r.regime,r.trimestre,r.annee
                ORDER BY r.annee DESC,
                         CASE r.trimestre WHEN 'T4' THEN 4 WHEN 'T3' THEN 3 WHEN 'T2' THEN 2 ELSE 1 END DESC,
                         r.regime, institution
                LIMIT ?
            """, [max(1, min(int(limit), 1000))]).fetchall()

    def get_run(self, execution_id: str) -> dict:
        with self.db.connect() as con:
            row = con.execute("""
                SELECT r.execution_id,COALESCE(i.nom_officiel,r.institution_id),r.institution_id,
                       r.regime,r.trimestre,r.annee,COUNT(*),
                       SUM(CASE WHEN COALESCE(r.statut_validation,'A_VALIDER') <> 'A_VALIDER' THEN 1 ELSE 0 END),
                       COALESCE(SUM(r.masse_financiere_controlee),0),
                       COALESCE(SUM(r.impact_potentiel),0),
                       COALESCE(SUM(r.impact_confirme),0)
                FROM resultats_rapprochement r
                LEFT JOIN institutions i ON i.institution_id=r.institution_id
                WHERE r.execution_id=?
                GROUP BY r.execution_id,i.nom_officiel,r.institution_id,r.regime,r.trimestre,r.annee
            """, [execution_id]).fetchone()
        if not row:
            raise ValueError("Rapprochement introuvable ou déjà supprimé.")
        keys = ["execution_id","institution","institution_id","regime","quarter","year","rows",
                "validated","mass","potential","confirmed"]
        return dict(zip(keys, row))

    def delete_run(self, execution_id: str) -> dict:
        info = self.get_run(execution_id)
        with self.db.connect() as con:
            con.execute("BEGIN")
            try:
                before = con.execute(
                    "SELECT COUNT(*) FROM resultats_rapprochement WHERE execution_id=?", [execution_id]
                ).fetchone()[0]
                con.execute("DELETE FROM resultats_rapprochement WHERE execution_id=?", [execution_id])
                remaining = con.execute(
                    "SELECT COUNT(*) FROM resultats_rapprochement WHERE execution_id=?", [execution_id]
                ).fetchone()[0]
                if remaining:
                    raise RuntimeError("La suppression du rapprochement n'a pas été complète.")
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        info["deleted"] = int(before or 0)
        return info
