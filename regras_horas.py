# Regras de atividades complementares por curso, copiadas dos regulamentos oficiais:
# CC: cc_atividades-complementares_regulamento_2019.pdf (seção 4, Art. 6)
# ES: es_atividades-complementares_regulamento_2019.pdf (mesmo texto da CC, total diferente)
# EC: ec_atividades-complementares_manual_2023.1.pdf (seção 4, Tabela 1)
# EP: ep_ppc_2023.pdf, anexo "Regulamento do Programa de Atividades Complementares" v2.00
# Onde o texto da Res. CEPE 7/2005 citada no regulamento diverge da lista do próprio curso
# (ex.: Grupo II da CC/ES: 80h na citação, 64h no programa do curso), vale a lista do curso.

_CC_ES_RULES = """\
I. Atividades de iniciação à pesquisa ou ensino ou atividades de extensão em áreas correlatas ao curso (até 96 horas para o conjunto):
a) Iniciação Científica com bolsa PIBIC, ITI ou bolsa ligada a projetos ou grupos de pesquisa aprovados na unidade acadêmica: até 3 horas por semana de atividade;
b) Participação do grupo PET: até 3 horas por semana de atividade;
c) Monitoria com bolsa: até 3 horas por semana de atividade;
d) Participação em projetos de extensão com bolsa: até 3 horas por semana de atividade;
e) Participação como voluntário nas atividades acima: até 3 horas por semana de atividade;
f) Participação em bolsa de Iniciação Acadêmica: até 3 horas por semana de atividade;
g) Participação em bolsa de Informática: até 3 horas por semana de atividade;
h) Cursos ministrados: até 2 horas para cada 1 hora ministrada.
Após a curricularização da extensão, somente horas excedentes de atividades de extensão podem contar como atividades complementares.

II. Atividades artístico-culturais e esportivas (até 64 horas para o conjunto):
a) Ensaio/treino de participação em grupo de teatro, de dança, coral, literário, musical ou esportivo: 1 hora por 2 horas de atividade;
b) Evento/apresentação/torneio de grupo de teatro, de dança, coral, literário, musical ou esportivo: até 4 horas por evento/apresentação/torneio;
c) Torneio/campeonato nacional ou internacional de e-sports, jogos eletrônicos, jogos de cartas ou de tabuleiro: até 2 horas por torneio/campeonato.
Atividades do Grupo II realizadas no Campus de Russas só são aceitas se organizadas por professores responsáveis do Campus.

III. Atividades de participação e/ou organização de eventos em áreas correlatas (até 32 horas para o conjunto):
a) Participação em congressos internacionais: 8 horas por dia de evento;
b) Participação em congressos nacionais: 4 horas por dia de evento;
c) Participação em seminários, colóquios e palestras avaliados pelo Colegiado do curso como contribuintes para um desenvolvimento integral do profissional, excluídas as atividades internas de grupos de pesquisas: 2 horas por dia de evento ou 1 hora por cada 4 horas de atividade;
d) Participação como ouvinte em defesas de Trabalho de Conclusão de Curso: 0,5 hora por defesa;
e) Apresentação de artigo em congresso internacional: 8 horas por artigo (além das horas da alínea a);
f) Apresentação de artigo em congresso nacional: 4 horas por artigo (além das horas da alínea b);
g) Organização de eventos científicos como presidente ou membros da diretoria: até 32 horas por evento;
h) Organização de eventos regulares do Campus de Russas como coordenador ou membro da comissão do evento: até 32 horas por evento;
i) Participação como monitor (ou auxiliar) em eventos: 4 horas por dia de atividade;
j) Participação em maratona de programação: competição local 2 horas; seletiva regional 4 horas; maratona nacional 8 horas; maratona internacional 16 horas.

IV. Experiências ligadas à formação profissional e/ou correlatas (até 64 horas para o conjunto):
a) Estágio Não-Curricular: até 8 horas por semana de atividade (atividade profissional na área de formação);
b) Participação na empresa júnior: 36 horas por pelo menos seis meses na função;
c) Cursos e minicursos correlatos: 1 hora por hora de certificado;
d) Participação em visitas técnicas: 2 horas para visitas em Russas e 4 horas para visitas em outras cidades.

V. Produção Técnica e/ou Científica em áreas correlatas (até 96 horas para o conjunto):
a) Publicação de artigo em revista internacional: até 96 horas por trabalho em revista com Qualis Capes, e até 72 horas sem Qualis;
b) Publicação de artigo em revista nacional: até 96 horas por trabalho com Qualis Capes, e até 48 horas sem Qualis;
c) Publicação de artigo completo em congresso internacional: até 72 horas com Qualis Capes, e até 54 horas sem Qualis;
d) Publicação de artigo completo em congresso nacional: até 72 horas com Qualis Capes, e até 36 horas sem Qualis;
e) Publicação de artigo resumido em congresso internacional: até 36 horas com Qualis Capes, e até 27 horas sem Qualis;
f) Publicação de artigo resumido em congresso nacional: até 36 horas com Qualis Capes, e até 18 horas sem Qualis;
g) Publicação de resumos em encontros universitários: até 8 horas por resumo e até 16 horas por resumo estendido;
h) Patente ou registro de software: até 96 horas por patente ou registro de software.
Só são aceitos trabalhos coautorados por professores do Campus de Russas, e as horas de cada item são divididas entre os alunos coautores.

VI. Vivências de gestão (até 48 horas para o conjunto):
a) Participação na diretoria de empresa júnior, como presidente e vice-presidente ou diretor: 48 horas por pelo menos seis meses na função;
b) Participação na diretoria do centro acadêmico do curso: 48 horas por pelo menos seis meses na função;
c) Representante estudantil no colegiado de coordenação de curso, departamental e conselho de centro: 2 horas por reunião;
d) Representante estudantil em comissão permanente ou temporária: 1 hora por reunião.

VII. Outras atividades (até 48 horas para o conjunto):
a) Atividade de voluntariado em prol da sociedade: 1 hora por 2 horas de atividade;
b) Curso de língua estrangeira: 1 hora por 2 horas de atividade;
c) Grupos de estudo sob a responsabilidade de um professor do Campus ou com ciência da Coordenação de curso: 1 hora por 3 horas de atividade;
d) Células de estudo do Programa de Aprendizagem Cooperativa em Células Estudantis: 1 hora por 3 horas de atividade;
e) Palestras e/ou cursos sobre temas importantes para a sociedade (acessibilidade, TI verde, dengue e doenças do Aedes aegypti, educação ambiental, direitos humanos, relações étnico-raciais e africanidades, entre outros): 1 hora por 4 horas de atividade.
"""

_CC_ES_GROUPS = {
    1: ("Iniciação à pesquisa, ensino ou extensão", 96),
    2: ("Atividades artístico-culturais e esportivas", 64),
    3: ("Participação e/ou organização de eventos", 32),
    4: ("Experiências ligadas à formação profissional", 64),
    5: ("Produção técnica e/ou científica", 96),
    6: ("Vivências de gestão", 48),
    7: ("Outras atividades", 48),
}

_EC_RULES = """\
I. Atividades de iniciação à pesquisa ou ensino ou atividades de extensão em áreas correlatas à Engenharia Civil (até 12 horas para o conjunto):
a) Iniciação científica, participação no grupo PET, monitoria com bolsa, participação em projeto de extensão com bolsa, participação como voluntário nessas atividades, bolsa de iniciação acadêmica (BIA): conta 1 hora por semana para cada 4 horas semanais dedicadas pelo aluno;
c) Cursos ministrados: até 2 horas para cada 1 hora ministrada.

II. Atividades artístico-culturais e esportivas (até 12 horas para o conjunto):
a) 2 horas por evento em grupo de teatro, de dança, coral, literário, musical ou em equipe esportiva, envolvendo ensaios/treinos e apresentações/torneios.

III. Atividades de participação e/ou organização de eventos em áreas correlatas (até 12 horas para o conjunto):
a) Participação em congressos internacionais: 6 horas por dia de evento;
b) Participação em congressos nacionais: 4 horas por dia de evento;
c) Participação em seminários, colóquios e palestras avaliados pelo Colegiado do curso, excluídas as atividades internas de grupos de pesquisas: 2 horas por dia de evento ou 1 hora por cada 4 horas de atividade;
d) Participação como ouvinte em defesas de Projeto Final de Curso: 1 hora por defesa;
e) Apresentação de artigo em congresso internacional: 3 horas por artigo (além das horas da alínea a);
f) Apresentação de artigo em congresso nacional: 2 horas por artigo (além das horas da alínea b);
g) Organização de eventos científicos como presidente ou membros da diretoria: até 12 horas por evento;
h) Organização de eventos regulares do Campus de Russas como coordenador ou membro da comissão do evento: 12 horas por evento;
i) Participação como monitor (ou auxiliar) em eventos: 4 horas por dia de atividade.

IV. Experiências ligadas à formação profissional e/ou correlatas (até 12 horas para o conjunto):
a) Estágio Não-Curricular: até 8 horas por semana de atividade (atividade profissional na área de formação);
b) Cursos e minicursos correlatos: 1 hora por hora de certificado;
c) Participação em visitas técnicas: 2 horas para visitas em Russas e 4 horas por dia para visitas em outras cidades.

V. Produção Técnica e/ou Científica em áreas correlatas (até 12 horas para o conjunto):
a) Publicação de artigo em revista internacional: 12 horas por trabalho em revista com Qualis Capes, e 4 horas sem Qualis;
b) Publicação de artigo em revista nacional: 12 horas por trabalho com Qualis Capes, e 4 horas sem Qualis;
c) Artigo completo em congresso internacional: 3 horas em congresso da área Engenharia I, e 1 hora em áreas afins;
d) Artigo completo em congresso nacional: 3 horas em congresso da área Engenharia I, e 1 hora em áreas afins;
e) Artigo resumido em congresso internacional: 3 horas em congresso da área Engenharia I, e 1 hora em áreas afins;
f) Artigo resumido em congresso nacional: 3 horas em congresso da área Engenharia I, e 1 hora em áreas afins;
g) Publicação de resumos em encontros universitários: 1 hora por resumo e 1,5 hora por resumo estendido;
h) Patente ou registro de software: 12 horas por patente ou registro de software.

VI. Vivências de gestão (até 12 horas para o conjunto):
a) Diretoria de empresa júnior, como presidente e vice-presidente ou diretor: 12 horas por pelo menos seis meses na função;
b) Participação na empresa júnior: 12 horas por pelo menos seis meses na função;
c) Diretoria do centro acadêmico do curso: 12 horas por pelo menos seis meses na função;
d) Representante estudantil no colegiado de coordenação de curso, departamental e conselho de centro: 12 horas por pelo menos seis meses na função;
e) Representante estudantil em comissão temporária: 1 hora por reunião.

VII. Outras atividades: Atividades de Revisão de Ensino Médio (até 48 horas, obrigatórias):
a) Participação na atividade obrigatória de Revisão de Matemática do Ensino Médio: 24 horas;
b) Participação na atividade obrigatória de Revisão de Física do Ensino Médio: 24 horas.
"""

_EP_RULES = """\
Atividades caracterizadas como extensão não são aceitas como atividades complementares, pois já são aproveitadas pela Unidade Curricular Especial de Extensão (UCEE).

I. Atividades de iniciação à pesquisa ou ensino em áreas correlatas à Engenharia de Produção (até 12 horas para o conjunto):
a) Iniciação Científica com bolsa PIBIC, ITI ou bolsa ligada a projetos de pesquisa aprovados na unidade acadêmica: até 3 horas por semana de atividade;
b) Participação do grupo PET: até 3 horas por semana de atividade;
c) Monitoria com bolsa: até 3 horas por semana de atividade;
d) Participação em projetos de extensão com bolsa: até 3 horas por semana de atividade;
e) Participação como voluntário nas atividades acima: até 3 horas por semana de atividade;
f) Participação em bolsa de Iniciação Acadêmica: até 3 horas por semana de atividade;
g) Participação em bolsa de Informática: até 3 horas por semana de atividade;
h) Cursos ministrados: até 2 horas para cada 1 hora ministrada;
i) Grupos de estudo sob a responsabilidade de um professor ou com ciência da Coordenação de curso: 1 hora por 2 horas de atividade;
j) Curso de língua estrangeira: 1 hora por 2 horas de atividade.

II. Atividades artístico-culturais e esportivas (até 12 horas para o conjunto):
a) 4 horas por evento em grupo de teatro, de dança, coral, literário, musical ou em equipe esportiva, envolvendo ensaios/treinos e apresentações/torneios.

III. Atividades de participação e/ou organização de eventos em áreas correlatas (até 12 horas para o conjunto):
a) Participação em congressos internacionais: 8 horas por dia de evento;
b) Participação em congressos nacionais: 4 horas por dia de evento;
c) Participação em seminários, colóquios e palestras avaliados pelo Colegiado do curso, excluídas as atividades internas de grupos de pesquisas: 2 horas por dia de evento ou 1 hora por cada 4 horas de atividade;
d) Participação em defesas de Trabalho de Conclusão de Curso: 1 hora por defesa ou seminário;
e) Apresentação de artigo em congresso internacional: 8 horas por artigo (além das horas da alínea a);
f) Apresentação de artigo em congresso nacional: 4 horas por artigo (além das horas da alínea b);
g) Organização de eventos científicos como presidente ou membros da diretoria: até 12 horas por evento;
h) Organização de eventos regulares do Campus de Russas como coordenador ou membro da comissão do evento: 12 horas por evento;
i) Participação como monitor (ou auxiliar) em eventos: 4 horas por dia de atividade;
j) Palestras e/ou cursos sobre temas importantes para a sociedade (acessibilidade, TI verde, dengue e doenças do Aedes aegypti, educação ambiental, direitos humanos, relações étnico-raciais e africanidades, entre outros): 1 hora por 2 horas de atividade.

IV. Experiências ligadas à formação profissional e/ou correlatas (até 12 horas para o conjunto):
a) Estágio Não-Curricular: até 8 horas por semana de atividade (atividade profissional na área de formação);
b) Cursos e minicursos correlatos: 1 hora por hora de certificado;
c) Participação em visitas técnicas: 2 horas para visitas em Russas e 4 horas para visitas em outras cidades;
d) Células de estudo do Programa de Aprendizagem Cooperativa em Células Estudantis: 1 hora por 3 horas de atividade;
e) Atividade de voluntariado em prol da sociedade: 1 hora por 2 horas de atividade.

V. Produção Técnica e/ou Científica em áreas correlatas (até 12 horas para o conjunto):
a) Publicação de artigo em revista internacional: 96 horas por trabalho com Qualis Capes, e 72 horas sem Qualis;
b) Publicação de artigo em revista nacional: 96 horas por trabalho com Qualis Capes, e 48 horas sem Qualis;
c) Artigo completo em congresso internacional: 72 horas com Qualis Capes, e 54 horas sem Qualis;
d) Artigo completo em congresso nacional: 72 horas com Qualis Capes, e 36 horas sem Qualis;
e) Artigo resumido em congresso internacional: 36 horas com Qualis Capes, e 27 horas sem Qualis;
f) Artigo resumido em congresso nacional: 36 horas com Qualis Capes, e 18 horas sem Qualis;
g) Publicação de resumos em encontros universitários: 8 horas por resumo e 16 horas por resumo estendido;
h) Patente ou registro de software: 96 horas por patente ou registro de software.

VI. Vivências de gestão (até 12 horas para o conjunto):
a) Diretoria de empresa júnior, como presidente e vice-presidente ou diretor: 48 horas por pelo menos seis meses na função;
b) Participação na empresa júnior: 36 horas por pelo menos seis meses na função;
c) Diretoria do centro acadêmico do curso: 48 horas por pelo menos seis meses na função;
d) Representante estudantil no colegiado de coordenação de curso, departamental e conselho de centro: 2 horas por reunião;
e) Representante estudantil em comissão temporária: 1 hora por reunião.

VII. Outras atividades (até 48 horas para o conjunto):
a) Participação na atividade obrigatória de Revisão de Matemática do Ensino Médio: 24 horas;
b) Participação na atividade obrigatória de Revisão de Física do Ensino Médio: 24 horas.
"""

_ENG_GROUPS = {
    1: ("Iniciação à pesquisa, ensino ou extensão", 12),
    2: ("Atividades artístico-culturais e esportivas", 12),
    3: ("Participação e/ou organização de eventos", 12),
    4: ("Experiências ligadas à formação profissional", 12),
    5: ("Produção técnica e/ou científica", 12),
    6: ("Vivências de gestão", 12),
    7: ("Revisão do Ensino Médio", 48),
}

_EP_GROUPS = {**_ENG_GROUPS, 1: ("Iniciação à pesquisa ou ensino", 12), 7: ("Outras atividades (Revisão do Ensino Médio)", 48)}

_CC_ES_HINTS = {
    1: "iniciação científica, PET, monitoria, projeto de extensão com bolsa ou voluntário (até 3h por semana); cursos ministrados",
    2: "grupos de teatro, dança, coral, música ou esporte (1h a cada 2h de treino; até 4h por apresentação/torneio)",
    3: "congressos (4h por dia nacional, 8h internacional), palestras, defesas de TCC, maratona de programação, organizar eventos",
    4: "estágio não curricular (até 8h por semana), empresa júnior, cursos e minicursos da área (1h por hora), visitas técnicas",
    5: "artigos e resumos publicados com professor do Campus, registro de software ou patente",
    6: "diretoria de empresa júnior ou centro acadêmico, representação estudantil em colegiado ou comissão",
    7: "voluntariado e curso de língua estrangeira (1h a cada 2h), grupos de estudo e células do PACCE (1h a cada 3h)",
}

_EC_HINTS = {
    1: "iniciação científica, PET, monitoria, extensão com bolsa ou voluntário (1h por semana a cada 4h semanais); cursos ministrados",
    2: "grupos de teatro, dança, coral, música ou equipe esportiva (2h por evento)",
    3: "congressos (4h por dia nacional, 6h internacional), palestras, defesas de projeto final, organizar eventos",
    4: "estágio não curricular (até 8h por semana), cursos e minicursos da área (1h por hora), visitas técnicas",
    5: "artigos e resumos publicados, registro de software ou patente",
    6: "empresa júnior, centro acadêmico, representação estudantil",
    7: "Revisão de Matemática e de Física do Ensino Médio (obrigatórias, 24h cada)",
}

_EP_HINTS = {
    1: "iniciação científica, PET, monitoria (até 3h por semana), grupos de estudo e curso de língua estrangeira (1h a cada 2h)",
    2: "grupos de teatro, dança, coral, música ou equipe esportiva (4h por evento)",
    3: "congressos (4h por dia nacional, 8h internacional), palestras, defesas de TCC, organizar eventos",
    4: "estágio não curricular, cursos e minicursos da área (1h por hora), visitas técnicas, PACCE, voluntariado",
    5: "artigos e resumos publicados, registro de software ou patente",
    6: "empresa júnior, centro acadêmico, representação estudantil",
    7: "Revisão de Matemática e de Física do Ensino Médio (obrigatórias, 24h cada)",
}

_CC_ES_SUBMISSION = """\
Como entregar suas horas complementares ({course}), segundo o regulamento do curso:

1. Junte os comprovantes. Só valem atividades feitas depois do seu ingresso no curso, e o comprovante precisa mostrar a atividade, a carga horária (ou horas semanais) e o período.
- Bolsas, monitoria, iniciação científica, PET e extensão: declaração do coordenador do projeto com horas semanais e período.
- Eventos e palestras: certificado ou declaração da comissão organizadora.
- Cursos e minicursos: certificado com carga horária e período.
- Estágio não curricular: contrato de estágio.
- Publicações: cópia da publicação ou carta de aceite.

2. Preencha o Anexo III (Integralização de Atividades Complementares), que está no regulamento no site do curso: grupo (I a VII) e item, nome da atividade e horas. O comando /horas mostra o que você já registrou aqui.

3. Separe os comprovantes em um envelope por grupo e coloque todos os envelopes dentro de uma pasta.

4. Junte uma cópia do seu histórico e dos termos de estágio, se você fez ou está fazendo Estágio Supervisionado.

5. Entregue na secretaria do curso dentro do prazo que a coordenação divulga a cada semestre. Comprovantes fora desse padrão não são analisados.

6. Depois, confira no SIGAA as horas lançadas. Tudo precisa estar integralizado até 60 dias antes da conclusão do curso.

Dúvidas: {contact}"""

_EC_SUBMISSION = """\
Como entregar suas horas complementares (Engenharia Civil), segundo o manual do curso:

1. Junte os comprovantes. Só valem atividades feitas depois do seu ingresso no curso.
- Iniciação científica, monitoria, PET e extensão: declaração do professor coordenador do projeto com horas semanais e período.
- Eventos: certificado ou declaração da comissão organizadora (defesas de projeto final: declaração da coordenação).
- Estágio não curricular: histórico e contrato de estágio. Cursos e minicursos: certificado de participação. Visitas técnicas: declaração do professor responsável.
- Publicações: cópia da publicação.
- Revisões de Matemática e Física: declaração da coordenação do curso.

2. Dê entrada na secretaria do curso com todos os documentos exigidos. Em Engenharia Civil o protocolo pode ser feito ao longo do curso, não só no fim.

3. Guarde o comprovante de entrega.

4. Confira no SIGAA as horas lançadas. Tudo precisa estar integralizado até 60 dias antes da conclusão do curso.

Dúvidas: /coordec"""

_EP_SUBMISSION = """\
Como entregar suas horas complementares (Engenharia de Produção), segundo o regulamento do curso:

1. Junte os comprovantes. Só valem atividades feitas depois do seu ingresso no curso. Atividades de extensão não contam aqui, porque já entram na Unidade Curricular Especial de Extensão (UCEE).
- Iniciação à pesquisa ou docência: declaração do professor coordenador do projeto com horas semanais e período.
- Eventos: certificado ou declaração da comissão organizadora (defesas de TCC e seminários de estágio: declaração da coordenação).
- Estágio não curricular: histórico e contrato de estágio. Cursos e minicursos: certificado de participação. Visitas técnicas: declaração do professor responsável.
- Publicações: cópia da publicação.
- Revisões de Matemática e Física: declaração do professor responsável, disponibilizada pela secretaria no site do curso.

2. Dê entrada na secretaria do curso com todos os documentos exigidos. O regulamento também prevê o módulo de Creditação de Atividades Complementares e Extensão do SIGAA para cadastrar e acompanhar as horas; confirme com a coordenação qual meio está valendo no seu semestre.

3. Guarde o comprovante de entrega.

4. Confira no SIGAA as horas lançadas. Tudo precisa estar integralizado até 60 dias antes da conclusão do curso.

Dúvidas: /coordep"""

COURSE_RULES = {
    "Ciência da Computação": {
        "total": 192, "groups": _CC_ES_GROUPS, "rules": _CC_ES_RULES, "hints": _CC_ES_HINTS,
        "submission": _CC_ES_SUBMISSION.format(course="Ciência da Computação", contact="/coordcc"),
    },
    "Engenharia de Software": {
        "total": 288, "groups": _CC_ES_GROUPS, "rules": _CC_ES_RULES, "hints": _CC_ES_HINTS,
        "submission": _CC_ES_SUBMISSION.format(course="Engenharia de Software", contact="/coordes"),
    },
    "Engenharia Civil": {
        "total": 60, "groups": _ENG_GROUPS, "rules": _EC_RULES, "hints": _EC_HINTS, "submission": _EC_SUBMISSION,
    },
    "Engenharia de Produção": {
        "total": 60, "groups": _EP_GROUPS, "rules": _EP_RULES, "hints": _EP_HINTS, "submission": _EP_SUBMISSION,
    },
}

ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII"}
