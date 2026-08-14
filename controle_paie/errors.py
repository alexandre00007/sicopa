from __future__ import annotations

import errno
import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable


@dataclass(frozen=True)
class ErrorReport:
    reference: str
    category: str
    summary: str
    actions: tuple[str, ...]
    technical: str
    operation: str

    @property
    def user_text(self) -> str:
        steps="\n".join(f"{index}. {action}" for index,action in enumerate(self.actions,1))
        operation=f"Opération : {self.operation}\n\n" if self.operation else ""
        return f"{operation}{self.summary}\n\nQue faire ?\n{steps}\n\nRéférence : {self.reference}"


def _contains(message: str, words: Iterable[str]) -> bool:
    return any(word in message for word in words)


def explain_error(error: BaseException, traceback_text: str="", operation: str="") -> ErrorReport:
    """Translate technical exceptions into consistent, actionable French guidance."""
    raw=str(error).strip() or repr(error)
    message=raw.lower()
    error_name=type(error).__name__
    fingerprint=hashlib.sha1(f"{error_name}:{raw}".encode("utf-8",errors="replace")).hexdigest()[:8].upper()
    reference=f"SIC-{datetime.now():%Y%m%d-%H%M%S}-{fingerprint}"
    category="Erreur inattendue"
    summary="SICORPA n’a pas pu terminer l’opération. Aucune conclusion métier ne doit être tirée d’un traitement interrompu."
    actions=(
        "Vérifiez le dernier message de progression et les données sélectionnées.",
        "Réessayez une seule fois après avoir fermé les fichiers source et destination.",
        "Si l’erreur revient, copiez le diagnostic ci-dessous et transmettez-le au support.",
    )

    if isinstance(error,FileNotFoundError):
        category="Fichier introuvable"
        summary="Le fichier ou le dossier demandé n’existe plus à l’emplacement sélectionné."
        actions=("Resélectionnez le fichier depuis son emplacement actuel.",
                 "Vérifiez que le disque externe ou le partage contenant le fichier est accessible.")
    elif isinstance(error,PermissionError) or getattr(error,"errno",None) in {errno.EACCES,errno.EPERM}:
        category="Accès refusé"
        summary="Windows ou le système a refusé l’accès au fichier ou au dossier."
        actions=("Fermez le fichier s’il est ouvert dans Excel, Word, Access ou un lecteur PDF.",
                 "Choisissez un dossier où votre compte peut écrire, par exemple Documents.",
                 "Évitez les dossiers système et les fichiers en lecture seule.")
    elif getattr(error,"errno",None)==errno.ENOSPC or _contains(message,("no space left","disk full","disque plein")):
        category="Espace disque insuffisant"
        summary="Le disque ne contient pas assez d’espace libre pour DuckDB ou les fichiers générés."
        actions=("Libérez de l’espace sur le disque de la base et sur le dossier de destination.",
                 "Supprimez les anciens dossiers de résultats devenus inutiles.",
                 "Relancez ensuite le traitement complet.")
    elif isinstance(error,MemoryError) or _contains(message,("out of memory","cannot allocate memory","failed to allocate","memory limit")):
        category="Mémoire insuffisante"
        summary="Le volume sélectionné dépasse la mémoire actuellement disponible pour ce traitement."
        actions=("Fermez les applications lourdes puis relancez SICORPA.",
                 "Traitez moins de sources à la fois ou libérez de l’espace pour les fichiers temporaires DuckDB.",
                 "Consultez Aide > Diagnostic pour vérifier la mémoire DuckDB configurée.")
    elif _contains(message,("failed to open zip","badzipfile","not a zip file","file is not a zip file","invalidfileexception")):
        category="Fichier Excel ou Word endommagé"
        summary="Le fichier sélectionné n’est pas une archive Office valide, est incomplet ou porte une mauvaise extension."
        actions=("Ouvrez le fichier dans Excel ou Word et utilisez Enregistrer sous pour créer une nouvelle copie.",
                 "Vérifiez que le fichier n’a pas été renommé manuellement de .xls vers .xlsx.",
                 "Sélectionnez la nouvelle copie dans SICORPA.")
    elif _contains(message,("illegalcharactererror","cannot be used in worksheets","illegal character")):
        category="Caractère invisible incompatible avec Excel"
        summary="Une donnée contient un caractère de contrôle invisible que le format Excel ne peut pas enregistrer."
        actions=("Régénérez le dossier avec la version corrigée de SICORPA; la base existante peut être conservée.",
                 "Aucune ligne métier ne doit être supprimée : SICORPA remplace uniquement le caractère invisible par un espace.",
                 "Si l’erreur persiste, transmettez cette référence et la valeur signalée au support.")
    elif _contains(message,("im002","sqldriverconnect","source de données introuvable",
                            "nom de pilote non spécifié","pilote odbc microsoft access introuvable")):
        category="Pilote ODBC Microsoft Access indisponible"
        summary="Windows ne trouve pas un pilote Microsoft Access compatible avec l’architecture de SICORPA."
        actions=("Fermez SICORPA et vérifiez si votre application est en 32 ou 64 bits dans Aide > Diagnostic.",
                 "Installez ou réparez Microsoft Access Database Engine avec exactement la même architecture.",
                 "Redémarrez Windows, puis utilisez Lister les tables avant de lancer le chargement.")
    elif _contains(message,("microsoft access driver","can't open microsoft","cannot open database","could not find installable isam","data source name not found","pyodbc")):
        category="Lecture Microsoft Access impossible"
        summary="SICORPA ne peut pas ouvrir la base Access avec le pilote actuellement disponible."
        actions=("Vérifiez que le fichier est bien au format .mdb ou .accdb et qu’il n’est pas ouvert exclusivement.",
                 "Installez le moteur Microsoft Access Database Engine de même architecture que SICORPA (64 bits).",
                 "Si la base est endommagée, ouvrez-la dans Access puis utilisez Compacter et réparer.")
    elif _contains(message,("database is locked","conflicting lock","could not set lock","another process")):
        category="Base DuckDB déjà utilisée"
        summary="Un autre processus utilise la base analytique et empêche l’écriture."
        actions=("Fermez toute autre instance de SICORPA.",
                 "Attendez la fin d’une sauvegarde ou d’une copie de la base.",
                 "Relancez SICORPA puis recommencez l’opération.")
    elif _contains(message,("binder error","catalog error","column","colonne")):
        category="Structure ou mapping incompatible"
        summary="Une colonne attendue est absente, mal mappée ou incompatible avec le traitement choisi."
        actions=("Vérifiez l’aperçu du fichier et la ligne d’en-tête.",
                 "Contrôlez Configuration > Mapping colonnes pour le régime et le type de source.",
                 "Corrigez les colonnes obligatoires signalées puis rechargez le fichier.")
    elif _contains(message,("ocr","tesseract")):
        category="Reconnaissance OCR indisponible"
        summary="Le PDF semble numérisé mais le moteur OCR requis n’est pas disponible ou a échoué."
        actions=("Installez Tesseract OCR et la langue française.",
                 "Vérifiez son état dans Aide > Diagnostic.",
                 "Réessayez avec un PDF moins volumineux ou de meilleure qualité.")
    elif isinstance(error,ValueError):
        category="Données ou sélection invalides"
        summary=raw
        actions=("Corrigez les champs ou la source indiqués dans le message.",
                 "Utilisez l’aperçu ou Vérifier le périmètre avant de relancer.")

    technical=f"{error_name}: {raw}"
    if traceback_text.strip():technical+=f"\n\n{traceback_text.strip()}"
    return ErrorReport(reference,category,summary,tuple(actions),technical,operation)
