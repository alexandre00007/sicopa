from __future__ import annotations

import re
import unicodedata

import pandas as pd


INVALID_MATRICULES = {"", "NU"}


def normalize_identity(value: object) -> str:
    """Normalisation canonique utilisée pour matricules et identités textuelles."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(c for c in text if not unicodedata.combining(c)).upper()
    return re.sub(r"[^A-Z0-9]", "", text)


def normalize_matricule(value: object) -> str:
    return normalize_identity(value)


def normalize_name(nom: object, prenom: object = "") -> str:
    left = "" if nom is None else str(nom)
    right = "" if prenom is None else str(prenom)
    return normalize_identity(left + right)


def normalize_series(values: pd.Series) -> pd.Series:
    """Version vectorisée de normalize_identity pour les imports volumineux."""
    return (
        values.fillna("")
        .astype(str)
        .str.normalize("NFKD")
        .str.upper()
        .str.encode("ascii", errors="ignore")
        .str.decode("ascii")
        .str.replace(r"[^A-Z0-9]", "", regex=True)
    )


def usable_matricule(value: object) -> bool:
    return normalize_matricule(value) not in INVALID_MATRICULES


def person_key(matricule: object, nom_normalise: object = "", fallback: object = "") -> str:
    mat = normalize_matricule(matricule)
    if mat not in INVALID_MATRICULES:
        return "M:" + mat
    nom = normalize_identity(nom_normalise)
    if nom:
        return "N:" + nom
    return "L:" + str(fallback or "")
