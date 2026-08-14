from controle_paie.database import Database
from controle_paie.raw_fusion_period import PeriodAwareRawFusionService


def _seed(db):
    with db.connect() as con:
        con.execute("CREATE TABLE raw_a (execution_id VARCHAR, matricule VARCHAR, montant DOUBLE)")
        con.execute("CREATE TABLE raw_b (execution_id VARCHAR, matricule VARCHAR, montant DOUBLE, extra VARCHAR)")
        con.execute("INSERT INTO raw_a VALUES ('e1','001',100),('old','999',50)")
        con.execute("INSERT INTO raw_b VALUES ('e2','001',200,'x')")
        con.execute("""INSERT INTO journal_executions
            (execution_id,type_operation,fichier_source,table_source,table_destination,institution_id,regime,trimestre,annee,mode_chargement,lignes_lues,lignes_chargees,statut,date_fin)
            VALUES
            ('e1','IMPORT_ACCESS','a.accdb','A','raw_a','i1','CNSS','T1',2026,'append',1,1,'TERMINE',CURRENT_TIMESTAMP),
            ('e2','IMPORT_ACCESS','b.accdb','B','raw_b','i1','CARC','T1',2026,'append',1,1,'TERMINE',CURRENT_TIMESTAMP),
            ('old','IMPORT_ACCESS','a.accdb','A','raw_a','i1','CNSS','T4',2025,'append',1,1,'TERMINE',CURRENT_TIMESTAMP)
        """)
        for line_id, execution_id, regime, amount in [
            ('p1','e1','CNSS',100),('p2','e2','CARC',200),('pold','old','CNSS',50)
        ]:
            con.execute("""INSERT INTO paie_standardisee
                (ligne_paie_id,execution_id,institution_id,regime,trimestre,annee,table_source,
                 matricule_source,matricule_normalise,nom,prenom,nom_normalise,section,categorie,grade,
                 unite_affectation,province,remuneration_base,transport,prime,logement,pension_rente,
                 autres_remunerations,retenues,montant_net,remuneration_brute_calculee,ligne_source)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [line_id,execution_id,'i1',regime,'T1' if execution_id!='old' else 'T4',2026 if execution_id!='old' else 2025,
                 'A' if regime=='CNSS' else 'B','001','001','Agent','Test','AGENT TEST','SEC','CAT','GR','UNIT','PROV',
                 amount,0,0,0,0,0,0,amount,amount,1])


def test_fusion_is_period_scoped_and_union_by_name(tmp_path):
    db=Database(tmp_path/'sicorpa.duckdb'); db.migrate(); _seed(db)
    service=PeriodAwareRawFusionService(db)
    info=service.create_fusion(['raw_a','raw_b'],'T1',2026,'test')
    assert info['rows']==2
    assert info['regimes']==2
    columns,rows=service.sample_fusion(info['id'],20)
    assert 'extra' in columns
    assert len(rows)==2
    with db.connect() as con:
        values={r[0] for r in con.execute(f'SELECT execution_id FROM "{info["table"]}"').fetchall()}
    assert values=={'e1','e2'}


def test_fusion_detects_agent_in_two_regimes_and_matrix(tmp_path):
    db=Database(tmp_path/'sicorpa.duckdb'); db.migrate(); _seed(db)
    service=PeriodAwareRawFusionService(db)
    info=service.create_fusion(['raw_a','raw_b'],'T1',2026,'matrix')
    rows=service.list_results(info['id'],'DEUX_REGIMES')
    assert len(rows)==1
    assert rows[0][1]=='001'
    assert rows[0][5]==2
    regimes,matrix=service.regime_matrix(info['id'])
    assert regimes==['CARC','CNSS']
    assert matrix[0][2]==1
    assert matrix[1][1]==1
