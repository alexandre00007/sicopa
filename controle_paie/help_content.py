USER_GUIDE = """SICORPA — MODE D’EMPLOI

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

8. MANQUE À GAGNER / IMPACT
L’impact potentiel correspond aux rémunérations associées aux anomalies détectées. Il doit être confirmé par un contrôle métier avant d’être considéré comme un montant définitif.

9. SAUVEGARDE
Utilisez Fichier > Sauvegarder la base. SICORPA crée aussi une sauvegarde avant les migrations. Les mises à jour ne doivent pas écraser la base utilisateur.

10. EN CAS D’ERREUR
Consultez Aide > Diagnostic et le fichier sicorpa.log. Vérifiez les chemins, l’espace disque, le pilote Access et les colonnes obligatoires.
"""
