# ASCII (legível)
# Organizado por tabulação

import pandas as pd
from PyQt6.QtWidgets import QFileDialog, QMessageBox
import os


class TratamentoEMT:  # Le arquivos EMT e cria DataFrame

    def __init__(self):
        self.dataframe = None
        self.file_path = None
        self.nome_arqv = None

    def open_emt_file(self):  # --> BOOLEANO

        try:
            # Abre o diálogo para selecionar o arquivo
            file_path, _ = QFileDialog.getOpenFileName(
                parent=None,
                caption="Abrir Arquivo EMT",
                directory=None,
                filter="Arquivos EMT (*.emt);;Todos os arquivos (*)",
            )

            # Se o usuário cancelou a seleção
            if not file_path:
                return False

            # Tenta carregar o arquivo
            success = self.load_emt_file(file_path)

            if success:
                # Mostra mensagem de sucesso
                QMessageBox.information(
                    None,
                    "Sucesso",
                    f"Arquivo '{self.nome_arqv}' carregado com sucesso!\n",
                )
            return success

        except Exception as e:
            print(f"ERRO: {str(e)}")
            QMessageBox.critical(None, "Erro", f"Erro ao abrir arquivo: {str(e)}")
            return False

    def load_emt_file(self, file_path):  # --> booleano
        """Carrega um arquivo EMT no formato BTS ASCII específico
        Padrao esperado:
        - Linhas 1..N: Bloco de metadados (Type, Measure unit, Tracks, Frequency, Frames, Start time, ...)
        - Linha em branco separa o bloco de metadados do bloco de dados
        - Próxima linha: titulo das colunas (Frame, Time, Ang pelve, ...)
        - Demais linhas: Dados numéricos

        Robusto a:
        - Terminadores CRLF (Windows)
        - Coluna extra vazia no final (causada por tab + \r)
        - Linhas malformadas (ignoradas via on_bad_lines)
        - Tamanho variável do bloco de metadados (a linha de cabeçalho
          é detectada automaticamente, não fixada em "linha 7")
        - Separador decimal sendo ',' em vez de '.' (configurado via
          `decimal=','` quando detectado)
        """

        try:

            if not os.path.exists(file_path):
                raise FileNotFoundError(f"Arquivo não encontrado: {file_path}")

            # Lê o arquivo bruto e normaliza:
            # - Substitui CRLF por LF
            # - Remove tabs/whitespace imediatamente antes do \n
            with open(file_path, "r", encoding="latin-1", newline="") as raw:
                conteudo = raw.read()
            conteudo = conteudo.replace("\r\n", "\n").replace("\r", "\n")
            linhas_originais = conteudo.split("\n")

            # Detecta automaticamente a primeira linha após o bloco de
            # metadados que pareça conter o cabeçalho das colunas
            # (vários campos, nenhum dos quais começa com "Type:" / "Tracks:" /
            # "Frequency:" / "Frames:" / "Start time:" / "Measure unit:").
            palavras_chave_cabecalho = (
                "type:",
                "measure unit:",
                "tracks:",
                "frequency:",
                "frames:",
                "start time:",
                "sequences:",
            )
            idx_header = None
            for i, linha in enumerate(linhas_originais):
                partes = [p.strip() for p in linha.split("\t") if p.strip()]
                if len(partes) < 2:
                    continue
                if any(p.lower().startswith(palavras_chave_cabecalho) for p in partes):
                    continue
                idx_header = i
                break

            if idx_header is None or idx_header == 0:
                # Fallback: assume layout antigo (cabeçalho na linha 7)
                idx_header = 6

            # Mantém apenas as linhas a partir do cabeçalho detectado.
            conteudo_util = "\n".join(linhas_originais[idx_header:])

            # Detecta se o separador decimal é ',' em vez de '.'
            # (ex.: arquivos gerados em locale pt-BR) olhando as primeiras
            # linhas de dados. Se houver ',' e nenhum '.', tratamos como
            # decimal-com-vírgula.
            dados_sample = "\n".join(linhas_originais[idx_header + 1 : idx_header + 20])
            usa_virgula = (
                "," in dados_sample
                and "." not in dados_sample
            )

            from io import StringIO

            kwargs = {
                "sep": "\t",
                "encoding": "latin-1",
                "engine": "python",
                "on_bad_lines": "skip",
            }
            if usa_virgula:
                kwargs["decimal"] = ","

            self.dataframe = pd.read_csv(StringIO(conteudo_util), **kwargs)

            # Salva infos
            self.file_path = file_path
            self.nome_arqv = os.path.basename(file_path)

            # Limpa dados vazios
            self.dataframe = self.dataframe.dropna(how="all", axis=0)
            self.dataframe = self.dataframe.dropna(how="all", axis=1)
            self.dataframe.columns = self.dataframe.columns.str.strip()
            # Converte para numérico, ignorando erros. Se houver mistura
            # de '.' e ',' (caso de erro de detecção), to_numeric lida.
            for col in self.dataframe.columns:
                if self.dataframe[col].dtype == object:
                    self.dataframe[col] = (
                        self.dataframe[col]
                        .astype(str)
                        .str.replace(",", ".", regex=False)
                    )
                self.dataframe[col] = pd.to_numeric(
                    self.dataframe[col], errors="coerce"
                )
            self.dataframe = self.dataframe.dropna(how="all", axis=0)
            # Reseta o índice
            self.dataframe = self.dataframe.reset_index(drop=True)

            return True

        except Exception as e:
            print(f"Erro ao carregar arquivo EMT: {str(e)}")
            return False

    def get_dataframe(self):
        return self.dataframe

    def get_file_info(self):  # --> dict or none

        if self.dataframe is not None:
            informacoes = {
                "nome_arqv": self.nome_arqv,
                "file_path": self.file_path,
                "arvore": None,
                "linhas": len(self.dataframe),
                "colunas": len(self.dataframe.columns),
                "nomes_colunas": list(self.dataframe.columns),
            }

            header_info = self.get_header_info()
            if header_info:
                informacoes.update(
                    {
                        "format": header_info["format"],
                        "type": header_info["type"],
                        "measure_unit": header_info["measure_unit"],
                        "sequences": header_info["sequences"],
                    }
                )

            return informacoes
        return None

    def is_loaded(self):  # --> booleano
        return self.dataframe is not None

    def get_header_info(self):  # --> dict or none

        if not self.file_path:
            return None

        try:
            with open(self.file_path, "r", encoding="latin-1") as file:
                header_lines = [file.readline().strip() for _ in range(6)]

            header_info = {
                "format": header_lines[0] if len(header_lines) > 0 else "",
                "type": "",
                "measure_unit": "",
                "sequences": "",
            }

            for line in header_lines:
                if line.startswith("Type:"):
                    header_info["type"] = line.replace("Type:", "").strip()
                elif line.startswith("Measure unit:"):
                    header_info["measure_unit"] = line.replace(
                        "Measure unit:", ""
                    ).strip()
                elif line.startswith("Sequences:"):
                    header_info["sequences"] = line.replace("Sequences:", "").strip()

            return header_info

        except Exception as e:
            print(f"Erro ao ler cabeçalho: {str(e)}")
            return None

    # Integração com a main
    def extrai_infos(self):
        sucesso = self.open_emt_file()

        if sucesso:
            df = self.get_dataframe()
            conteudo = self.get_file_info()
            cabecalho = self.get_header_info()
            return df, conteudo, cabecalho
        else:
            return None, None, None
