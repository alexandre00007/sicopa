from __future__ import annotations

import json
import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Optional

from .database import Database

FORMULA_RULES = {
    "MASSE_CONTROLEE":"Masse financière contrôlée",
    "DOUBLON_MATRICULE":"Doublon par matricule",
    "DOUBLON_NOM":"Doublon par nom",
    "MATRICULE_MANQUANT":"Matricule manquant ou NU",
    "PAYE_NON_DECLARE":"Payé mais non déclaré",
    "PAYE_HORS_PERIMETRE":"Payé hors du périmètre filtré",
    "RAPPORT_GENERAL":"Autres rubriques du listing",
    "AUCUN_IMPACT":"Aucun impact financier",
}
DEFAULT_COMPONENTS = [
    ("BASE","Rémunération de base","remuneration_base"),
    ("TRANSPORT","Transport","transport"),
    ("PRIME","Primes","prime"),
    ("LOGEMENT","Logement","logement"),
    ("PENSION_RENTE","Pension / rente","pension_rente"),
    ("AUTRES_REMUNERATIONS","Autres rémunérations","autres_remunerations"),
    ("RETENUES","Retenues","retenues"),
    ("MONTANT_NET","Montant net","montant_net"),
]
DEFAULT_COEFFICIENTS = {code:1 for code,_,_ in DEFAULT_COMPONENTS[:6]}

class FinancialFormulaService:
    def __init__(self,database: Database):self.db=database

    def seed_components(self) -> None:
        with self.db.connect() as con:
            for order,(code,label,column) in enumerate(DEFAULT_COMPONENTS,1):
                con.execute("""INSERT INTO config_composantes_financieres (code,libelle,colonne_standard,actif,ordre)
                    VALUES (?,?,?,?,?) ON CONFLICT(code) DO NOTHING""",[code,label,column,True,order])

    def list_components(self,active_only: bool=True) -> list[tuple]:
        query="SELECT code,libelle,colonne_standard,actif,ordre FROM config_composantes_financieres"
        if active_only:query+=" WHERE actif"
        with self.db.connect() as con:return con.execute(query+" ORDER BY ordre,libelle").fetchall()

    def component_columns(self) -> list[str]:return [row[2] for row in self.list_components()]

    def add_component(self,code: str,label: str,column: str="") -> str:
        code=re.sub(r"[^A-Z0-9_]","_",code.strip().upper()).strip("_")
        column=(column.strip().lower() or code.lower())
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*",code):raise ValueError("Le code doit commencer par une lettre et contenir lettres, chiffres ou underscores.")
        if not re.fullmatch(r"[a-z][a-z0-9_]*",column):raise ValueError("La colonne standard doit être un identifiant valide.")
        if not label.strip():raise ValueError("Le libellé de la composante est obligatoire.")
        with self.db.connect() as con:
            existing={row[1] for row in con.execute("PRAGMA table_info('paie_standardisee')").fetchall()}
            if column not in existing:con.execute(f'ALTER TABLE paie_standardisee ADD COLUMN "{column}" DECIMAL(38,2) DEFAULT 0')
            order=con.execute("SELECT COALESCE(MAX(ordre),0)+1 FROM config_composantes_financieres").fetchone()[0]
            con.execute("""INSERT INTO config_composantes_financieres VALUES (?,?,?,?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(code) DO UPDATE SET libelle=excluded.libelle,colonne_standard=excluded.colonne_standard,actif=TRUE""",[code,label.strip(),column,True,order])
        return code

    def set_component_active(self,code: str,active: bool) -> None:
        with self.db.connect() as con:con.execute("UPDATE config_composantes_financieres SET actif=? WHERE code=?",[active,code])

    def save_formula(self,name: str,regime: str,rule: str,coefficients: dict,
                     institution_id: Optional[str]=None) -> str:
        if rule not in FORMULA_RULES:raise ValueError("Règle d’impact inconnue.")
        if not regime.strip():raise ValueError("Le régime est obligatoire.")
        available={row[0] for row in self.list_components()};clean={}
        for code,value in coefficients.items():
            if code not in available:raise ValueError(f"Composante inconnue : {code}")
            try:number=Decimal(str(value).replace(",","."))
            except InvalidOperation as exc:raise ValueError(f"Coefficient invalide pour {code}.") from exc
            if abs(number)>100:raise ValueError("Un coefficient doit être compris entre -100 et 100.")
            if number:clean[code]=str(number)
        if rule!="AUCUN_IMPACT" and not clean:raise ValueError("Ajoutez au moins une composante avec un coefficient non nul.")
        if rule=="AUCUN_IMPACT":clean={}
        identifier=str(uuid.uuid4());scope=institution_id or ""
        with self.db.connect() as con:
            version=con.execute("SELECT COALESCE(MAX(version),0)+1 FROM config_formules_impact WHERE COALESCE(institution_id,'')=? AND regime=? AND regle=?",[scope,regime,rule]).fetchone()[0]
            con.execute("UPDATE config_formules_impact SET actif=FALSE WHERE COALESCE(institution_id,'')=? AND regime=? AND regle=?",[scope,regime,rule])
            con.execute("INSERT INTO config_formules_impact VALUES (?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",[identifier,name.strip() or FORMULA_RULES[rule],institution_id,regime,rule,version,json.dumps(clean,ensure_ascii=False),True])
        return identifier

    def list_formulas(self,regime: str="",institution_id: Optional[str]=None) -> list[tuple]:
        conditions=[];params=[]
        if regime:conditions.append("regime=?");params.append(regime)
        if institution_id is not None:conditions.append("COALESCE(institution_id,'')=?");params.append(institution_id or "")
        query="SELECT formule_id,nom,institution_id,regime,regle,version,composants_json,actif,cree_le FROM config_formules_impact"
        if conditions:query+=" WHERE "+" AND ".join(conditions)
        with self.db.connect() as con:return con.execute(query+" ORDER BY cree_le DESC",params).fetchall()

    def active_formula(self,institution_id: str,regime: str,rule: str) -> dict:
        with self.db.connect() as con:
            row=con.execute("""SELECT formule_id,nom,institution_id,regime,regle,version,composants_json
                FROM config_formules_impact WHERE actif AND regime=? AND regle=?
                AND (institution_id=? OR institution_id IS NULL)
                ORDER BY CASE WHEN institution_id=? THEN 0 ELSE 1 END,version DESC LIMIT 1""",[regime,rule,institution_id,institution_id]).fetchone()
        if row:
            return {"formula_id":row[0],"name":row[1],"institution_id":row[2],"regime":row[3],"rule":row[4],"version":row[5],"coefficients":json.loads(row[6]),"source":"configurée"}
        coefficients={} if rule=="AUCUN_IMPACT" else dict(DEFAULT_COEFFICIENTS)
        return {"formula_id":None,"name":"Formule SICORPA par défaut","institution_id":None,"regime":regime,"rule":rule,"version":0,"coefficients":coefficients,"source":"défaut"}

    def sql_expression(self,institution_id: str,regime: str,rule: str,alias: str="") -> tuple[str,dict]:
        snapshot=self.active_formula(institution_id,regime,rule);components={row[0]:row[2] for row in self.list_components(active_only=False)};prefix=f"{alias}." if alias else "";terms=[]
        for code,value in snapshot["coefficients"].items():
            column=components.get(code)
            if not column:continue
            coefficient=Decimal(str(value));terms.append(f"({coefficient} * COALESCE({prefix}\"{column}\",0))")
        return (" + ".join(terms) if terms else "0::DECIMAL(38,2)"),snapshot

    def describe(self,snapshot: dict) -> str:
        labels={row[0]:row[1] for row in self.list_components(active_only=False)};parts=[]
        for code,value in snapshot.get("coefficients",{}).items():
            number=Decimal(str(value));sign="+" if number>=0 else "−";amount=abs(number);term=labels.get(code,code)
            if amount!=1:term=f"{amount} × {term}"
            parts.append((sign,term))
        expression=" ".join(f"{sign} {term}" for sign,term in parts).lstrip("+ ") or "0"
        return f"{FORMULA_RULES.get(snapshot['rule'],snapshot['rule'])} — {snapshot['name']} v{snapshot['version']} : {expression}"

    def trace_execution(self,execution_id: str,snapshots: list[dict]) -> None:
        unique={snapshot["rule"]:snapshot for snapshot in snapshots}
        with self.db.connect() as con:
            for rule,snapshot in unique.items():
                con.execute("DELETE FROM traces_formules_execution WHERE execution_id=? AND regle=?",[execution_id,rule])
                con.execute("INSERT INTO traces_formules_execution VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)",[execution_id,rule,snapshot.get("formula_id"),snapshot["version"],snapshot["name"],json.dumps(snapshot["coefficients"],ensure_ascii=False)])

    def simulate(self,institution_id: str,regime: str,quarter: str,year: int,rule: str) -> tuple[int,Decimal,dict]:
        expression,snapshot=self.sql_expression(institution_id,regime,rule,"p");filters,values=self.db.payroll_filter_clause(institution_id,regime,"p")
        with self.db.connect() as con:
            count,total=con.execute(f"SELECT COUNT(*),COALESCE(SUM({expression}),0) FROM paie_standardisee p WHERE p.institution_id=? AND p.regime=? AND p.trimestre=? AND p.annee=?{filters}",[institution_id,regime,quarter,year]+values).fetchone()
        return count,total,snapshot
