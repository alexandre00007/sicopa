from __future__ import annotations

import json
import re
import unicodedata
import uuid
from typing import Dict, Iterable, Optional

import pandas as pd

from .config import CANONICAL_ALIASES


def normalize_identifier(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(c for c in text if not unicodedata.combining(c)).upper()
    return re.sub(r"[^A-Z0-9]", "", text)


def infer_mapping(columns: Iterable[str], explicit: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    result = dict(explicit or {})
    normalized_source = {normalize_identifier(column): column for column in columns}
    for target, aliases in CANONICAL_ALIASES.items():
        if target in result.values():
            continue
        for alias in aliases:
            source = normalized_source.get(normalize_identifier(alias))
            if source:
                result[source] = target
                break
    return result


def _series(data: pd.DataFrame, name: str, default: object = "") -> pd.Series:
    return data[name] if name in data.columns else pd.Series(default, index=data.index)


def _money(data: pd.DataFrame, name: str) -> pd.Series:
    return pd.to_numeric(_series(data, name, 0), errors="coerce").fillna(0)


def standardize_payroll(data: pd.DataFrame, metadata: Dict, mapping: Optional[Dict[str, str]] = None) -> pd.DataFrame:
    renamed = data.rename(columns=infer_mapping(data.columns, mapping)).copy()
    output = pd.DataFrame(index=renamed.index)
    output["ligne_paie_id"] = [str(uuid.uuid4()) for _ in range(len(renamed))]
    for key in ["execution_id", "institution_id", "regime", "trimestre", "annee", "table_source"]:
        output[key] = metadata.get(key)
    output["matricule_source"] = _series(renamed, "matricule_source").fillna("").astype(str)
    output["matricule_normalise"] = output["matricule_source"].map(normalize_identifier)
    output["nom"] = _series(renamed, "nom").fillna("").astype(str)
    output["prenom"] = _series(renamed, "prenom").fillna("").astype(str)
    output["nom_normalise"] = (output["nom"] + output["prenom"]).map(normalize_identifier)
    for column in ["section", "categorie", "grade", "unite_affectation", "province"]:
        output[column] = _series(renamed, column).fillna("").astype(str)
    for column in ["remuneration_base", "transport", "prime", "logement", "pension_rente", "autres_remunerations", "retenues", "montant_net"]:
        output[column] = _money(renamed, column)
    gross = ["remuneration_base", "transport", "prime", "logement", "pension_rente", "autres_remunerations"]
    output["remuneration_brute_calculee"] = output[gross].sum(axis=1)
    extra_targets=sorted(column for column in renamed.columns if str(column).startswith("composante_"))
    if extra_targets:
        extra_frame=pd.DataFrame({str(column)[11:].upper():_money(renamed,column) for column in extra_targets},index=renamed.index)
        output["composantes_supplementaires_json"]=[json.dumps({key:float(value) for key,value in row.items()},ensure_ascii=False) for row in extra_frame.to_dict("records")]
    else:output["composantes_supplementaires_json"]="{}"
    output["formule_remuneration_id"]="FORMULE_DEFAUT"
    output["ligne_source"] = range(2, len(output) + 2)
    return output


def standardize_declaration(data: pd.DataFrame, metadata: Dict, mapping: Optional[Dict[str, str]] = None) -> pd.DataFrame:
    renamed = data.rename(columns=infer_mapping(data.columns, mapping)).copy()
    output = pd.DataFrame(index=renamed.index)
    output["ligne_declaratif_id"] = [str(uuid.uuid4()) for _ in range(len(renamed))]
    for key in ["execution_id", "institution_id", "regime", "trimestre", "annee", "fichier_source", "feuille_source"]:
        output[key] = metadata.get(key)
    output["matricule_source"] = _series(renamed, "matricule_source").fillna("").astype(str)
    output["matricule_normalise"] = output["matricule_source"].map(normalize_identifier)
    output["nom"] = _series(renamed, "nom").fillna("").astype(str)
    output["prenom"] = _series(renamed, "prenom").fillna("").astype(str)
    output["nom_normalise"] = (output["nom"] + output["prenom"]).map(normalize_identifier)
    for column in ["grade", "service", "unite_affectation", "province", "statut_agent"]:
        output[column] = _series(renamed, column).fillna("").astype(str)
    output["remuneration_declaree"] = _money(renamed, "remuneration_declaree")
    output["ligne_source"] = range(2, len(output) + 2)
    return output
