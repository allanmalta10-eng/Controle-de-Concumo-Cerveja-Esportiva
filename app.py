from flask import Flask, render_template, request, redirect, url_for, send_file, session, flash
import sqlite3, pandas as pd
from datetime import datetime, timedelta
import os, shutil
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import urllib.parse
import traceback

app = Flask(__name__)
app.secret_key = 'segredo123'

DB = 'consumo.db'
VALOR_UNITARIO = 12.00

# Configurações de e-mail (AJUSTE COM SEUS DADOS)
EMAIL_CONFIG = {
    'smtp_server': 'smtp.gmail.com',
    'smtp_port': 587,
    'email': 'seuemail@gmail.com',      # SEU E-MAIL
    'password': 'sua-senha-app',        # SENHA DE APP
    'enabled': True
}

def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS pessoas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT NOT NULL,
                    apelido TEXT NOT NULL,
                    celular TEXT UNIQUE NOT NULL
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS consumos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pessoa_id INTEGER,
                    data TEXT,
                    quantidade INTEGER DEFAULT 1,
                    valor_unitario REAL DEFAULT 12.00,
                    valor_total REAL DEFAULT 12.00,
                    FOREIGN KEY (pessoa_id) REFERENCES pessoas(id)
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS admins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario TEXT UNIQUE NOT NULL,
                    senha TEXT,
                    email TEXT
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS convites_senha (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario TEXT UNIQUE NOT NULL,
                    email TEXT NOT NULL,
                    token TEXT UNIQUE NOT NULL,
                    expiracao TEXT NOT NULL,
                    usado INTEGER DEFAULT 0
                )''')
    # user default
    try:
        c.execute("INSERT OR IGNORE INTO admins (id, usuario, senha) VALUES (1, 'admin', 'admin')")
    except:
        pass
    conn.commit()
    conn.close()

def migrate_db():
    if os.path.exists(DB):
        bak = DB + ".bak_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy(DB, bak)
    
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    
    # Verificar estrutura da tabela admins
    c.execute("PRAGMA table_info(admins)")
    cols = c.fetchall()
    
    # Se a tabela não existe ou precisa ser alterada
    if not cols:
        # Recriar tabela com estrutura correta
        c.execute('DROP TABLE IF EXISTS admins')
        c.execute('''CREATE TABLE admins (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        usuario TEXT UNIQUE NOT NULL,
                        senha TEXT,
                        email TEXT
                    )''')
        c.execute("INSERT OR IGNORE INTO admins (id, usuario, senha) VALUES (1, 'admin', 'admin')")
    else:
        # Verificar se a coluna senha permite NULL
        senha_not_null = False
        email_exists = False
        for col in cols:
            if col[1] == 'senha' and col[3] == 1:  # 1 significa NOT NULL
                senha_not_null = True
            if col[1] == 'email':
                email_exists = True
        
        # Se senha não permite NULL, recriar tabela
        if senha_not_null:
            print("Recriando tabela admins para permitir senha NULL...")
            # Criar tabela temporária
            c.execute('''CREATE TABLE admins_temp (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            usuario TEXT UNIQUE NOT NULL,
                            senha TEXT,
                            email TEXT
                        )''')
            # Copiar dados
            c.execute("INSERT INTO admins_temp (id, usuario, senha, email) SELECT id, usuario, senha, email FROM admins")
            # Excluir tabela original
            c.execute("DROP TABLE admins")
            # Renomear tabela temporária
            c.execute("ALTER TABLE admins_temp RENAME TO admins")
        
        # Adicionar coluna email se não existir
        if not email_exists:
            c.execute("ALTER TABLE admins ADD COLUMN email TEXT")
    
    # Verificar/Criar tabela convites_senha
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='convites_senha'")
    if not c.fetchone():
        c.execute('''CREATE TABLE convites_senha (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        usuario TEXT UNIQUE NOT NULL,
                        email TEXT NOT NULL,
                        token TEXT UNIQUE NOT NULL,
                        expiracao TEXT NOT NULL,
                        usado INTEGER DEFAULT 0
                    )''')
    
    conn.commit()
    conn.close()

# initialize and migrate
init_db()
migrate_db()

@app.template_filter()
def brdate(value):
    if not value:
        return ''
    try:
        if isinstance(value, datetime):
            value = value.strftime("%Y-%m-%d")
        return datetime.strptime(value[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return value

def enviar_email_criar_senha(destinatario, usuario, token):
    """Envia e-mail com link para criar senha"""
    if not EMAIL_CONFIG.get('enabled', False):
        return False
        
    try:
        base_url = request.host_url.rstrip('/')
        link_criar_senha = f"{base_url}/criar_senha?token={urllib.parse.quote(token)}"
        
        msg = MIMEMultipart()
        msg['From'] = EMAIL_CONFIG['email']
        msg['To'] = destinatario
        msg['Subject'] = 'Crie sua senha - Sistema de Consumo'
        
        corpo = f"""
        <html>
        <body>
            <h2>Crie sua senha de acesso</h2>
            <p>Você foi cadastrado como administrador do Sistema de Consumo.</p>
            <p><strong>Seu usuário:</strong> {usuario}</p>
            <p>Clique no link abaixo para criar sua senha:</p>
            <p><a href="{link_criar_senha}" style="background-color: #495057; color: white; padding: 10px 20px; text-decoration: none; border-radius: 25px; display: inline-block;">Criar Minha Senha</a></p>
            <p><strong>Link:</strong> {link_criar_senha}</p>
            <p><em>Este link expira em 24 horas.</em></p>
            <br>
            <p>Atenciosamente,<br>Sistema de Consumo</p>
        </body>
        </html>
        """
        
        msg.attach(MIMEText(corpo, 'html'))
        
        server = smtplib.SMTP(EMAIL_CONFIG['smtp_server'], EMAIL_CONFIG['smtp_port'])
        server.starttls()
        server.login(EMAIL_CONFIG['email'], EMAIL_CONFIG['password'])
        server.send_message(msg)
        server.quit()
        
        return True
    except Exception as e:
        print(f"Erro ao enviar e-mail: {e}")
        return False

@app.route('/', methods=['GET', 'POST'])
def index():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    
    if request.method == 'POST':
        pessoa_id = request.form.get('pessoa_id','').strip() 
        data = request.form.get('data','').strip()
        quantidade_raw = request.form.get('quantidade','').strip()
        
        if not quantidade_raw:
            quantidade_raw = '1'

        if not pessoa_id or not data:
            flash('Preencha nome e data', 'danger')
            return redirect(url_for('index'))
            
        try:
            quantidade = int(quantidade_raw)
            if quantidade <= 0:
                raise ValueError()
        except Exception:
            flash('Quantidade inválida (deve ser um número inteiro positivo).', 'danger')
            return redirect(url_for('index'))
            
        valor_total = quantidade * VALOR_UNITARIO
        c.execute("INSERT INTO consumos (pessoa_id, data, quantidade, valor_unitario, valor_total) VALUES (?,?,?,?,?)",
                  (pessoa_id, data, quantidade, VALOR_UNITARIO, valor_total))
        conn.commit()
        flash('Consumo registrado com sucesso', 'success')

    filtro_pessoa_id = request.args.get('pessoa_id','').strip()
    filtro_data = request.args.get('data','').strip()
    
    query = """SELECT consumos.id, pessoas.nome, pessoas.apelido, pessoas.celular, consumos.data, consumos.quantidade, consumos.valor_unitario, consumos.valor_total
               FROM consumos JOIN pessoas ON consumos.pessoa_id = pessoas.id"""
    filtros = []
    params = []
    
    if filtro_pessoa_id:
        filtros.append('pessoas.id = ?')
        params.append(filtro_pessoa_id)
        
    if filtro_data:
        filtros.append('consumos.data = ?')
        params.append(filtro_data)
        
    if filtros:
        query += ' WHERE ' + ' AND '.join(filtros)
        
    query += ' ORDER BY consumos.data DESC'
    registros = c.execute(query, params).fetchall()
    
    pessoas = c.execute('SELECT id, nome, apelido FROM pessoas ORDER BY apelido').fetchall()
    conn.close()
    
    data_hoje = datetime.now().strftime("%Y-%m-%d")
    
    return render_template('index.html', 
                           pessoas=pessoas, 
                           registros=registros, 
                           valor_unit=VALOR_UNITARIO,
                           filtro_data=filtro_data,
                           data_hoje=data_hoje
                           )

@app.route('/exportar_consumo')
def exportar_consumo():
    conn = sqlite3.connect(DB)
    filtro_pessoa_id = request.args.get('pessoa_id', '').strip()
    filtro_data = request.args.get('data', '').strip()
    
    query = """SELECT pessoas.nome as Nome, pessoas.apelido as Apelido, pessoas.celular as Celular,
                      consumos.data as Data, consumos.quantidade as Quantidade,
                      consumos.valor_unitario as ValorUnit, consumos.valor_total as ValorTotal
               FROM consumos JOIN pessoas ON consumos.pessoa_id = pessoas.id"""
    
    filtros = []
    params = []
    
    if filtro_pessoa_id:
        filtros.append('pessoas.id = ?')
        params.append(filtro_pessoa_id)
        
    if filtro_data:
        filtros.append('consumos.data = ?')
        params.append(filtro_data)
    
    if filtros:
        query += ' WHERE ' + ' AND '.join(filtros)
    
    query += ' ORDER BY consumos.data DESC'
    
    df = pd.read_sql_query(query, conn, params=params if params else None)
    conn.close()
    
    if not df.empty:
        try:
            df['Data'] = pd.to_datetime(df['Data']).dt.strftime('%d/%m/%Y')
        except Exception:
            pass
        df['ValorUnit'] = df['ValorUnit'].apply(lambda x: f"R$ {x:,.2f}".replace('.', '#').replace(',', '.').replace('#', ','))
        df['ValorTotal'] = df['ValorTotal'].apply(lambda x: f"R$ {x:,.2f}".replace('.', '#').replace(',', '.').replace('#', ','))
    
    filepath = f'consumo_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    df.to_excel(filepath, index=False)
    return send_file(filepath, as_attachment=True)

@app.route('/exportar_cadastros')
def exportar_cadastros():
    conn = sqlite3.connect(DB)
    df = pd.read_sql_query("SELECT nome as Nome, apelido as Apelido, celular as Celular FROM pessoas ORDER BY nome", conn)
    conn.close()
    filepath = f'cadastros_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    df.to_excel(filepath, index=False)
    return send_file(filepath, as_attachment=True)

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        usuario = request.form.get('usuario','').strip()
        senha = request.form.get('senha','').strip()
        conn = sqlite3.connect(DB)
        c = conn.cursor()
        c.execute('SELECT * FROM admins WHERE usuario=? AND senha=?',(usuario,senha))
        adm = c.fetchone()
        conn.close()
        if adm:
            session['admin'] = usuario
            session['admin_id'] = adm[0]
            session['admin_email'] = adm[3] if len(adm) > 3 else ''
            flash('Login efetuado', 'success')
            return redirect(url_for('admin'))
        flash('Usuário ou senha inválidos', 'danger')
        return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('admin', None)
    session.pop('admin_id', None)
    session.pop('admin_email', None)
    flash('Logout realizado', 'info')
    return redirect(url_for('index'))

@app.route('/admin', methods=['GET','POST'])
def admin():
    if 'admin' not in session:
        return redirect(url_for('login'))
    
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    
    if request.method == 'POST' and request.form.get('action')=='add_pessoa':
        nome = request.form.get('nome','').strip()
        apelido = request.form.get('apelido','').strip()
        celular = request.form.get('celular','').strip()
        try:
            c.execute('INSERT INTO pessoas (nome, apelido, celular) VALUES (?,?,?)',(nome,apelido,celular))
            conn.commit()
            flash('Pessoa cadastrada','success')
        except sqlite3.IntegrityError:
            flash('Celular já cadastrado','danger')
            
    filtro_apelido = request.args.get('filtro_nome', '').strip()
    filtro_data_consumo = request.args.get('filtro_data_consumo', '').strip()
    filtro_data_agregada = request.args.get('filtro_data_agregada', '').strip()
    
    c.execute('SELECT id,nome,apelido,celular FROM pessoas ORDER BY nome')
    pessoas = c.fetchall()
    
    query_consumos = """SELECT T1.id, T2.apelido, T1.data, T1.quantidade, T1.valor_total
                 FROM consumos T1 JOIN pessoas T2 ON T1.pessoa_id = T2.id"""
    params_consumos = []
    where_consumos = []
    
    if filtro_apelido:
        where_consumos.append('T2.apelido = ?')
        params_consumos.append(filtro_apelido)
        
    if filtro_data_consumo:
        where_consumos.append('T1.data = ?')
        params_consumos.append(filtro_data_consumo)
    
    if where_consumos:
        query_consumos += ' WHERE ' + ' AND '.join(where_consumos)
    
    query_consumos += ' ORDER BY T1.data DESC'
    consumos = c.execute(query_consumos, params_consumos).fetchall()
    
    query_agregada = 'SELECT data, SUM(quantidade) as total_qt, SUM(valor_total) as total_val FROM consumos'
    params_agregada = []
    
    if filtro_data_agregada:
        query_agregada += ' WHERE data = ?'
        params_agregada.append(filtro_data_agregada)
    
    query_agregada += ' GROUP BY data ORDER BY data DESC'
    consumo_por_data = c.execute(query_agregada, params_agregada).fetchall()
    
    c.execute('SELECT id,usuario,email,senha FROM admins ORDER BY usuario')
    admins = c.fetchall()
    
    c.execute('SELECT DISTINCT apelido FROM pessoas WHERE apelido IS NOT NULL AND apelido != "" ORDER BY apelido')
    pessoas_unicas_raw = c.fetchall()
    pessoas_unicas = [p[0] for p in pessoas_unicas_raw]
    
    conn.close()
    
    return render_template('admin.html', 
                         pessoas=pessoas, 
                         consumos=consumos, 
                         consumo_por_data=consumo_por_data, 
                         admins=admins,
                         pessoas_unicas=pessoas_unicas,
                         filtro_apelido=filtro_apelido,
                         filtro_data_consumo=filtro_data_consumo,
                         filtro_data_agregada=filtro_data_agregada)

@app.route('/excluir_pessoa/<int:id>', methods=['POST'])
def excluir_pessoa(id):
    if 'admin' not in session:
        return redirect(url_for('login'))
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('DELETE FROM pessoas WHERE id=?',(id,))
    conn.commit()
    conn.close()
    flash('Cadastro excluído','info')
    return redirect(url_for('admin'))

@app.route('/excluir_consumo/<int:id>', methods=['POST'])
def excluir_consumo(id):
    if 'admin' not in session:
        return redirect(url_for('login'))
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('DELETE FROM consumos WHERE id=?',(id,))
    conn.commit()
    conn.close()
    flash('Consumo excluído','info')
    return redirect(url_for('admin'))

@app.route('/add_admin', methods=['POST'])
def add_admin():
    if 'admin' not in session: 
        return redirect(url_for('login'))
    
    try:
        usuario = request.form.get('usuario','').strip()
        email = request.form.get('email','').strip().lower()
        
        print(f"Tentando cadastrar: usuario={usuario}, email={email}")
        
        # Validação do celular (11 dígitos)
        if not usuario.isdigit() or len(usuario) != 11:
            flash('Usuário deve ser um celular com 11 dígitos (DDD + número)', 'danger')
            return redirect(url_for('admin'))
        
        # Validação do e-mail
        if not email or '@' not in email:
            flash('E-mail inválido', 'danger')
            return redirect(url_for('admin'))
        
        conn = sqlite3.connect(DB)
        c = conn.cursor()
        
        # Verificar se usuário já existe
        c.execute('SELECT id FROM admins WHERE usuario = ?', (usuario,))
        if c.fetchone():
            flash('Usuário já existe', 'danger')
            conn.close()
            return redirect(url_for('admin'))
        
        # Criar admin com senha temporária
        senha_temporaria = 'temp_' + secrets.token_urlsafe(8)
        c.execute('INSERT INTO admins (usuario, senha, email) VALUES (?, ?, ?)', 
                 (usuario, senha_temporaria, email))
        
        # Gerar token para criar senha
        token = secrets.token_urlsafe(32)
        expiracao = (datetime.now() + timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
        
        # Salvar token
        c.execute('INSERT INTO convites_senha (usuario, email, token, expiracao) VALUES (?, ?, ?, ?)', 
                 (usuario, email, token, expiracao))
        
        conn.commit()
        conn.close()
        
        # Enviar e-mail para criar senha
        email_enviado = False
        if EMAIL_CONFIG.get('enabled', False):
            email_enviado = enviar_email_criar_senha(email, usuario, token)
        
        if email_enviado:
            flash(f'Admin cadastrado! E-mail enviado para {email} para criar senha.', 'success')
        else:
            # Mostrar link manualmente se e-mail falhar
            base_url = request.host_url.rstrip('/')
            link_manual = f"{base_url}/criar_senha?token={token}"
            flash(f'Admin cadastrado! E-mail não enviado. Link para criar senha: {link_manual}', 'warning')
            
    except Exception as e:
        print(f"ERRO DETALHADO: {str(e)}")
        print(traceback.format_exc())
        flash(f'Erro ao cadastrar administrador: {str(e)}', 'danger')
    
    return redirect(url_for('admin'))

@app.route('/criar_senha', methods=['GET', 'POST'])
def criar_senha():
    token = request.args.get('token', '')
    
    if not token:
        flash('Token inválido', 'danger')
        return redirect(url_for('login'))
    
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    
    # Verificar token
    c.execute('SELECT usuario, email, expiracao, usado FROM convites_senha WHERE token = ?', (token,))
    convite = c.fetchone()
    
    if not convite:
        flash('Token inválido ou expirado', 'danger')
        conn.close()
        return redirect(url_for('login'))
    
    usuario, email, expiracao, usado = convite
    
    # Verificar se já foi usado
    if usado:
        flash('Este link já foi utilizado', 'danger')
        conn.close()
        return redirect(url_for('login'))
    
    # Verificar expiração
    if datetime.now() > datetime.strptime(expiracao, '%Y-%m-%d %H:%M:%S'):
        flash('Este link expirou', 'danger')
        conn.close()
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        senha = request.form.get('senha', '').strip()
        confirmar_senha = request.form.get('confirmar_senha', '').strip()
        
        if not senha:
            flash('Senha não pode estar vazia', 'danger')
            return render_template('criar_senha.html', token=token, usuario=usuario, email=email)
        
        if senha != confirmar_senha:
            flash('Senhas não coincidem', 'danger')
            return render_template('criar_senha.html', token=token, usuario=usuario, email=email)
        
        # Criar senha do admin
        try:
            c.execute('UPDATE admins SET senha = ? WHERE usuario = ?', (senha, usuario))
            # Marcar token como usado
            c.execute('UPDATE convites_senha SET usado = 1 WHERE token = ?', (token,))
            conn.commit()
            flash('Senha criada com sucesso! Faça login para continuar.', 'success')
            conn.close()
            return redirect(url_for('login'))
        except Exception as e:
            flash('Erro ao criar senha', 'danger')
            print(f"Erro: {e}")
            conn.close()
            return redirect(url_for('login'))
    
    conn.close()
    return render_template('criar_senha.html', token=token, usuario=usuario, email=email)

@app.route('/resetar_minha_senha', methods=['POST'])
def resetar_minha_senha():
    if 'admin' not in session: 
        return redirect(url_for('login'))
    
    try:
        usuario = session.get('admin')
        email = session.get('admin_email', '')
        
        if not email:
            flash('E-mail não cadastrado para este usuário', 'danger')
            return redirect(url_for('admin'))
        
        conn = sqlite3.connect(DB)
        c = conn.cursor()
        
        # Gerar novo token
        token = secrets.token_urlsafe(32)
        expiracao = (datetime.now() + timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
        
        # Remover tokens antigos
        c.execute('DELETE FROM convites_senha WHERE usuario = ?', (usuario,))
        
        # Salvar novo token
        c.execute('INSERT INTO convites_senha (usuario, email, token, expiracao) VALUES (?, ?, ?, ?)', 
                 (usuario, email, token, expiracao))
        
        conn.commit()
        conn.close()
        
        # Enviar e-mail
        email_enviado = False
        if EMAIL_CONFIG.get('enabled', False):
            email_enviado = enviar_email_criar_senha(email, usuario, token)
        
        if email_enviado:
            flash(f'E-mail de redefinição enviado para {email}', 'success')
        else:
            base_url = request.host_url.rstrip('/')
            link_manual = f"{base_url}/criar_senha?token={token}"
            flash(f'E-mail não enviado. Link para redefinir senha: {link_manual}', 'warning')
            
    except Exception as e:
        print(f"Erro ao resetar senha: {e}")
        flash('Erro ao solicitar redefinição de senha', 'danger')
    
    return redirect(url_for('admin'))

@app.route('/change_my_password', methods=['POST'])
def change_my_password():
    if 'admin' not in session: 
        return redirect(url_for('login'))
    
    nova_senha = request.form.get('nova_senha','').strip()
    admin_id = session.get('admin_id')
    
    if not nova_senha:
        flash('Nova senha não pode estar vazia', 'danger')
        return redirect(url_for('admin'))
    
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('UPDATE admins SET senha=? WHERE id=?',(nova_senha, admin_id))
    conn.commit()
    conn.close()
    flash('Sua senha foi alterada com sucesso','success')
    return redirect(url_for('admin'))

@app.route('/excluir_admin/<int:id>', methods=['POST'])
def excluir_admin(id):
    if 'admin' not in session:
        return redirect(url_for('login'))
    
    if id == session.get('admin_id'):
        flash('Você não pode excluir seu próprio usuário', 'danger')
        return redirect(url_for('admin'))
    
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('DELETE FROM admins WHERE id=?',(id,))
    conn.commit()
    conn.close()
    flash('Administrador excluído','info')
    return redirect(url_for('admin'))

if __name__ == '__main__':
    print("=" * 50)
    print("🚀 Iniciando Servidor Flask...")
    print("📧 URL: http://127.0.0.1:5000")
    print("📧 Rota criar_senha: http://127.0.0.1:5000/criar_senha")
    if EMAIL_CONFIG.get('enabled', False):
        print("✅ Sistema de e-mail: ATIVADO")
    else:
        print("⚠️  Sistema de e-mail: DESATIVADO")
    print("🛑 Para parar: Ctrl+C")
    print("=" * 50)
    app.run(debug=True)