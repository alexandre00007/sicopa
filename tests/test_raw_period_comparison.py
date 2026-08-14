from controle_paie.database import Database
from controle_paie.raw_period_comparison import RawPeriodComparisonService


def _seed(db):
    with db.connect() as con:
        con.execute("CREATE TABLE raw_a (execution_id VARCHAR, matricule VARCHAR, nom VARCHAR)")
        con.execute("CREATE TABLE raw_b (execution_id VARCHAR, matricule VARCHAR, nom VARCHAR, extra VARCHAR)")
        con.execute("INSERT INTO raw_a VALUES ('ea','001','Alpha'),('ea','002','Beta'),('ea','003','Gamma'),('ea','004','Only A')")
        con.execute("INSERT INTO raw_b VALUES ('eb','001','Alpha','x'),('eb','099','Beta','x'),('eb','003','Delta','x'),('eb','005','Only B','x')")
        con.execute("""INSERT INTO journal_executions
            (execution_id,type_operation,fichier_source,table_source,table_destination,institution_id,regime,trimestre,annee,mode_chargement,lignes_lues,lignes_chargees,statut,date_fin)
            VALUES
            ('ea','IMPORT_ACCESS','a.accdb','A','raw_a','ia','RA','T1',2026,'append',4,4,'TERMINE',CURRENT_TIMESTAMP),
            ('eb','IMPORT_ACCESS','b.accdb','B','raw_b','ib','RB','T1',2026,'append',4,4,'TERMINE_AVEC_AVERTISSEMENTS',CURRENT_TIMESTAMP)
        """)
        rows = [
            ('a1','ea','ia','RA','001','ALPHA','Alpha'),
            ('a2','ea','ia','RA','002','BETA','Beta'),
            ('a3','ea','ia','RA','003','GAMMA','Gamma'),
            ('a4','ea','ia','RA','004','ONLY A','Only A'),
            ('b1','eb','ib','RB','001','ALPHA','Alpha'),
            ('b2','eb','ib','RB','099','BETA','Beta'),
            ('b3','eb','ib','RB','003','DELTA','Delta'),
            ('b4','eb','ib','RB','005','ONLY B','Only B'),
        ]
        for line_id, execution_id, institution, regime, mat, norm, nom in rows:
            con.execute("""INSERT INTO paie_standardisee
                (ligne_paie_id,execution_id,institution_id,regime,trimestre,annee,table_source,
                 matricule_source,matricule_normalise,nom,prenom,nom_normalise,section,categorie,grade,
                 unite_affectation,province,remuneration_base,transport,prime,logement,pension_rente,
                 autres_remunerations,retenues,montant_net,remuneration_brute_calculee,ligne_source)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [line_id,execution_id,institution,regime,'T1',2026,'A' if execution_id=='ea' else 'B',
                 mat,mat,nom,'',norm,'SEC','CAT','GR','UNIT','PROV',100,0,0,0,0,0,0,100,100,1])


def test_raw_period_comparison_matches_by_mat_and_name(tmp_path):
    db=Database(tmp_path/'sicorpa.duckdb'); db.migrate(); _seed(db)
    service=RawPeriodComparisonService(db)
    info=service.analyze('raw_a','raw_b','T1',2026)
    both=service.list_results(info['id'],'COMMUN_PAR_MATRICULE_ET_NOM')
    by_name=service.list_results(info['id'],'COMMUN_PAR_NOM')
    by_mat=service.list_results(info['id'],'COMMUN_PAR_MATRICULE')
    assert any(r[1]=='001' and r[2]=='001' for r in both)
    assert any(r[1]=='002' and r[2]=='099' for r in by_name)
    assert any(r[1]=='003' and r[2]=='003' for r in by_mat)


def test_raw_period_comparison_detects_cross_identity_anomalies(tmp_path):
    db=Database(tmp_path/'sicorpa.duckdb'); db.migrate(); _seed(db)
    service=RawPeriodComparisonService(db)
    info=service.analyze('raw_a','raw_b','T1',2026)
    same_name=service.list_results(info['id'],'MEME_NOM_MATRICULE_DIFFERENT')
    same_mat=service.list_results(info['id'],'MEME_MATRICULE_NOM_DIFFERENT')
    only_a=service.list_results(info['id'],'UNIQUEMENT_A')
    only_b=service.list_results(info['id'],'UNIQUEMENT_B')
    assert any(r[1]=='002' for r in same_name)
    assert any(r[1]=='003' for r in same_mat)
    assert any(r[1]=='004' for r in only_a)
    assert any(r[2]=='005' for r in only_b)
