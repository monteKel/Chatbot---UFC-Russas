DOC_TITLES = {
    "cc_atividades-complementares_regulamento_2019.pdf": "Regulamento de Atividades Complementares de Ciência da Computação (2019)",
    "cc_estagio_manual-normatizacao_2020.1.pdf": "Manual de Estágio de Ciência da Computação (2020.1)",
    "cc_tcc_regulamento_2020.1.pdf": "Regulamento de TCC de Ciência da Computação (2020.1)",
    "cc_fluxograma_integralizacao-curricular_2018.pdf": "Fluxograma curricular de Ciência da Computação (2018)",
    "cc_ppc_2022.pdf": "Projeto Pedagógico de Ciência da Computação (2022)",
    "es_atividades-complementares_regulamento_2019.pdf": "Regulamento de Atividades Complementares de Engenharia de Software (2019)",
    "es_ppc_2017.pdf": "Projeto Pedagógico de Engenharia de Software (2017)",
    "es_fluxograma_ppc-completo.pdf": "Fluxograma curricular de Engenharia de Software",
    "es_estagio_manual-normatizacao_grade-2018_v2025.pdf": "Manual de Estágio de Engenharia de Software (grade 2018)",
    "es_estagio_manual-normatizacao_grade-2025_v2025.pdf": "Manual de Estágio de Engenharia de Software (grade 2025)",
    "es_estagio_fluxograma-matricula-etapas.pdf": "Fluxograma de matrícula no Estágio de Engenharia de Software",
    "es_tcc_regulamento_2024.1.pdf": "Regulamento de TCC de Engenharia de Software (2024.1)",
    "es_tcc_fluxograma-tcc1-etapas.pdf": "Fluxograma das etapas do TCC 1 de Engenharia de Software",
    "es_tcc_fluxograma-tcc1-matricula.pdf": "Fluxograma de matrícula no TCC 1 de Engenharia de Software",
    "es_tcc_fluxograma-tcc2-matricula-etapas.pdf": "Fluxograma do TCC 2 de Engenharia de Software",
    "ec_atividades-complementares_manual_2023.1.pdf": "Manual de Atividades Complementares de Engenharia Civil (2023.1)",
    "ec_estagio_manual-normatizacao_2023.1.pdf": "Manual de Estágio de Engenharia Civil (2023.1)",
    "ec_extensao_manual-curricularizacao_2026.pdf": "Manual de Curricularização da Extensão de Engenharia Civil (2026)",
    "ec_tcc_diretrizes-avaliacao-banca.pdf": "Diretrizes de avaliação de banca de TCC de Engenharia Civil",
    "ec_tcc_regulamento_2018.pdf": "Regulamento de TCC de Engenharia Civil (2018)",
    "ep_estagio_manual-normatizacao_2020.pdf": "Manual de Estágio de Engenharia de Produção (2020)",
    "ep_fluxograma_integralizacao-curricular_2019.2.pdf": "Fluxograma curricular de Engenharia de Produção (2019.2)",
    "ep_ppc_2023.pdf": "Projeto Pedagógico de Engenharia de Produção (2023)",
    "ep_tcc_regulamento_2020.pdf": "Regulamento de TCC de Engenharia de Produção (2020)",
}


def doc_title(filename: str | None) -> str:
    if not filename:
        return "documento oficial"
    return DOC_TITLES.get(filename, filename)
