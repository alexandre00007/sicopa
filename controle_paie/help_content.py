USER_GUIDE = """SICORPA — MODE D’EMPLOI

ERGONOMIE DES FENÊTRES
La fenêtre principale démarre maximisée. Les fenêtres secondaires sont centrées et adaptées à la résolution de l’écran. Lorsque leur contenu dépasse la hauteur disponible, utilisez la barre de défilement ou la molette; les boutons d’action restent visibles en bas.

1. CONFIGURATION INITIALE
Ajoutez les institutions et les régimes dans l’onglet Configuration. Dans Mapping colonnes, associez les colonnes Access et Excel aux colonnes standardisées. Rendez obligatoires les colonnes indispensables au contrôle.

2. IMPORTATION DE LA PAIE ACCESS
Choisissez l’institution, le régime, le trimestre et l’année. Sélectionnez le fichier .mdb/.accdb puis la table correspondante. Vérifiez le périmètre avant le chargement. Sous Windows, le pilote Microsoft Access doit être installé; sous Linux, mdbtools est requis.

3. IMPORTATION DU DÉCLARATIF EXCEL
Choisissez le même périmètre. Sélectionnez le classeur, la feuille et la ligne d’en-tête. Utilisez l’aperçu pour contrôler les colonnes avant l’importation.

4. FILTRAGE DU LISTING
Dans Rapprochement, choisissez une colonne standardisée, un opérateur et un contenu. Plusieurs filtres sont combinés avec ET. Le bouton Vérifier le périmètre indique le nombre de lignes retenues.

5. RAPPROCHEMENT
Le matricule valide est prioritaire, puis le nom normalisé. NU, N.U et leurs variantes sont considérés comme non exploitables et ne créent jamais de doublons de matricule.

6. AGENTS PAYÉS HORS PÉRIMÈTRE
La cohorte contient les agents du déclaratif présents dans le listing filtré. Elle est recherchée dans tout le listing du trimestre hors périmètre filtré, y compris dans une autre section de la même institution.

7. RAPPORT ET ANNEXES
Le rapport final présente le listing, le déclaratif et les comparaisons. Enregistrements désigne le nombre de lignes; Nombre de concernés désigne l’effectif unique. Chaque rubrique fournit un lien vers le détail et un lien vers l’effectif unique.

8. CALCULS FINANCIERS ET IMPACT
Dans l’onglet Calculs financiers, ajoutez si nécessaire une composante, puis construisez une formule avec des coefficients positifs ou négatifs. Définissez l’institution éventuelle, le régime, la rubrique, la date d’entrée en vigueur et l’agrégation. Utilisez Simuler avant d’enregistrer. Une nouvelle version ne modifie pas les résultats déjà calculés. L’impact potentiel doit être confirmé par un contrôle métier avant d’être considéré comme définitif.

9. OUTILS FICHIERS
Le menu Outils fichiers permet de faire pivoter toutes les pages d’un PDF de 90°, 180° ou 270°, de convertir un PDF en classeur Excel structuré et de convertir son texte et ses tableaux en document Word modifiable. Pour une page scannée, activez l’OCR automatique et choisissez Français + anglais, Français ou Anglais. Le traitement s’exécute en arrière-plan avec une progression page par page. Aide > Diagnostic indique si Tesseract OCR est disponible.

10. VERSION D’ESSAI
La durée est définie lors de la construction de l’exécutable et commence au premier lancement. L’en-tête et Aide > État de la version d’essai indiquent les jours restants. SICORPA mémorise le dernier lancement en UTC et bloque les nouveaux traitements si l’horloge recule anormalement ou si l’essai expire. Une correction inférieure à six heures est tolérée. La consultation, l’export et la sauvegarde des données existantes restent disponibles; aucune donnée n’est supprimée.

11. SAUVEGARDE
Utilisez Fichier > Sauvegarder la base. SICORPA crée aussi une sauvegarde avant les migrations. Les mises à jour ne doivent pas écraser la base utilisateur.

12. EN CAS D’ERREUR
Consultez Aide > Diagnostic et le fichier sicorpa.log. Vérifiez les chemins, l’espace disque, le pilote Access et les colonnes obligatoires.
"""
