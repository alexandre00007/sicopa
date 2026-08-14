from __future__ import annotations

from dataclasses import dataclass


IDENTITY_ALGORITHM_VERSION = "identity-strict-v3"

MATCH_EXACT = "MATCH_EXACT"
MATCH_MATRICULE = "MATCH_MATRICULE"
MATCH_NOM_PROBABLE = "MATCH_NOM_PROBABLE"
MATCH_AMBIGU_MATRICULE = "MATCH_AMBIGU_MATRICULE"
MATCH_AMBIGU_NOM = "MATCH_AMBIGU_NOM"
IDENTITE_INCOHERENTE = "IDENTITE_INCOHERENTE"
ABSENT = "ABSENT"

CONFIDENCE_CERTAIN = "CERTAIN"
CONFIDENCE_STRONG = "FORT"
CONFIDENCE_PROBABLE = "PROBABLE"
CONFIDENCE_AMBIGUOUS = "AMBIGU"
CONFIDENCE_NONE = "AUCUN"


@dataclass(frozen=True)
class IdentityDecision:
    status: str
    confidence: str
    exact: bool = False
    ambiguous: bool = False
    reason: str = ""


def decide_identity(*, usable_matricule: bool, usable_name: bool,
                    exact_candidates: int, matricule_candidates: int,
                    name_candidates: int) -> IdentityDecision:
    """Politique canonique de décision d'identité utilisée par les analyses SICORPA.

    Règles :
    - un seul candidat portant simultanément même matricule + même nom => certain ;
    - plusieurs candidats sur une clé => ambigu, aucun choix automatique ;
    - matricule unique mais nom différent => incohérence d'identité ;
    - nom seul unique => probable seulement ;
    - sinon absent.
    """
    if usable_matricule and usable_name and exact_candidates == 1:
        return IdentityDecision(MATCH_EXACT, CONFIDENCE_CERTAIN, exact=True,
                                reason="Même matricule et même nom normalisés sur un candidat unique")
    if usable_matricule and matricule_candidates > 1:
        return IdentityDecision(MATCH_AMBIGU_MATRICULE, CONFIDENCE_AMBIGUOUS, ambiguous=True,
                                reason="Plusieurs identités portent ce matricule")
    if usable_matricule and matricule_candidates == 1:
        return IdentityDecision(IDENTITE_INCOHERENTE, CONFIDENCE_AMBIGUOUS, ambiguous=True,
                                reason="Matricule retrouvé mais nom normalisé différent")
    if usable_name and name_candidates > 1:
        return IdentityDecision(MATCH_AMBIGU_NOM, CONFIDENCE_AMBIGUOUS, ambiguous=True,
                                reason="Plusieurs identités portent ce nom")
    if usable_name and name_candidates == 1:
        return IdentityDecision(MATCH_NOM_PROBABLE, CONFIDENCE_PROBABLE,
                                reason="Correspondance unique par nom sans preuve matricule")
    return IdentityDecision(ABSENT, CONFIDENCE_NONE, reason="Aucun candidat exploitable")


def exact_match_status_sql(column: str = "statut") -> str:
    """Fragment SQL canonique pour compter uniquement les correspondances exactes."""
    return f"{column}='COMMUN_PAR_MATRICULE_ET_NOM'"
