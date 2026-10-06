import pandas as pd
from PyQt6.QtWidgets import QFileDialog, QMessageBox
import os
import sys
from typing import Optional, Dict, Tuple
from basictdf import Tdf

# Mapeamento centralizado de unidades do formato TDF (BTS Bioengineering)
# O formato TDF armazena TODOS os dados no Sistema Internacional (SI).
# A biblioteca basictdf aplica automaticamente gain/offset e retorna valores em SI.
# NÃO existem atributos de unidade explícitos no binário – são convenção do formato.
UNIDADES_TDF = {
    "3d_posicao": "m",  # Coordenadas X, Y, Z dos marcadores
    "forca": "N",  # Componentes de força Fx, Fy, Fz
    "cop": "m",  # Centro de Pressão (CoPx, CoPy)
    "torque": "N.m",  # Componentes de torque/momento
    "emg": "V",  # Sinais eletromiográficos
    "tempo": "s",  # Tempo (calculado via frequência em Hz)
}


class TratamentoTDF:

    def __init__(self):
        self.dataframe = None
        self.file_path = None
        self.nome_arqv = None
        self.unidades_colunas = {}  # {nome_coluna: unidade}

    def open_tdf_file(self) -> bool:
        try:
            file_path, _ = QFileDialog.getOpenFileName(
                parent=None,
                caption="Abrir Arquivo TDF",
                directory=None,
                filter="Arquivos TDF (*.tdf);;Todos os arquivos (*)",
            )

            if not file_path:
                return False

            success = self.load_tdf_file(file_path)

            if success:
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

    def _resolver_caminho(self, file_path: str) -> str:
        """Resolve o caminho do arquivo tentando diferentes localizações.

        Garante que arquivos referenciados por nome (com espaços, parênteses
        ou outros caracteres especiais) sejam encontrados mesmo quando o
        diretório de execução (cwd) é diferente do diretório onde o arquivo
        realmente está.

        Ordem de busca:
          1. Caminho absoluto ou relativo já existente.
          2. Diretório de trabalho atual (cwd).
          3. Diretório do executável / entrypoint (sys.argv[0]).
          4. Diretório raiz do projeto (parent do pacote ``arquivos``).

        Returns:
            O caminho (string) que existe no disco, ou o caminho original
            caso nenhuma localização seja encontrada (para que o erro
            exibido contenha o caminho que foi tentado).
        """
        # Garante que tratamos o argumento como string, mesmo que venha
        # de outro tipo (PathLike, bytes, etc.).
        caminho_str = os.fspath(file_path)

        # 1. Já existe como dado (absoluto ou relativo ao cwd)
        if os.path.exists(caminho_str):
            return os.path.abspath(caminho_str)

        # 2. Tenta relativo ao diretório de trabalho atual
        cwd = os.getcwd()
        candidato_cwd = os.path.join(cwd, caminho_str)
        if os.path.exists(candidato_cwd):
            return os.path.abspath(candidato_cwd)

        # 3. Tenta relativo ao diretório do entrypoint (sys.argv[0])
        try:
            base_argv = os.path.dirname(os.path.abspath(sys.argv[0]))
            candidato_argv = os.path.join(base_argv, caminho_str)
            if os.path.exists(candidato_argv):
                return os.path.abspath(candidato_argv)
        except (IndexError, OSError):
            pass

        # 4. Tenta relativo à raiz do projeto (parent do pacote ``arquivos``)
        try:
            raiz_pacote = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..")
            )
            candidato_raiz = os.path.join(raiz_pacote, caminho_str)
            if os.path.exists(candidato_raiz):
                return os.path.abspath(candidato_raiz)
        except OSError:
            pass

        # Nenhum candidato bateu — devolve o original para que a mensagem
        # de erro seja informativa.
        return caminho_str

    def load_tdf_file(self, file_path: str) -> bool:
        try:
            caminho_abs = self._resolver_caminho(file_path)

            if not os.path.exists(caminho_abs):
                cwd = os.getcwd()
                raise FileNotFoundError(
                    f"Arquivo não encontrado: '{file_path}' "
                    f"(caminho resolvido: '{caminho_abs}'). "
                    f"Diretório de trabalho atual: '{cwd}'. "
                    f"Verifique se o arquivo existe e se o caminho está correto."
                )

            if not os.path.isfile(caminho_abs):
                raise IsADirectoryError(
                    f"O caminho informado não é um arquivo: '{caminho_abs}'"
                )

            if not os.access(caminho_abs, os.R_OK):
                raise PermissionError(
                    f"Permissão negada para ler o arquivo: '{caminho_abs}'"
                )

            self.file_path = caminho_abs
            self.nome_arqv = os.path.basename(caminho_abs)

            self.dataframe, self.unidades_colunas = self._parse_tdf_file(caminho_abs)
            return True

        except ValueError:
            raise  # Propaga para o chamador exibir mensagem ao usuário
        except FileNotFoundError as e:
            print(f"[ERRO TDF] {type(e).__name__}: {e}")
            raise
        except PermissionError as e:
            print(f"[ERRO TDF] {type(e).__name__}: {e}")
            raise
        except IsADirectoryError as e:
            print(f"[ERRO TDF] {type(e).__name__}: {e}")
            raise
        except Exception as e:
            print(f"[ERRO TDF] Erro inesperado ao carregar arquivo TDF: "
                  f"{type(e).__name__}: {e}")
            import traceback

            traceback.print_exc()
            return False

    def get_dataframe(self):
        return self.dataframe

    def get_file_info(self) -> Optional[Dict]:
        if self.dataframe is not None:
            return {
                "nome_arqv": self.nome_arqv,
                "file_path": self.file_path,
                "arvore": None,
                "linhas": len(self.dataframe),
                "colunas": len(self.dataframe.columns),
                "nomes_colunas": list(self.dataframe.columns),
            }
        return None

    def get_header_info(self) -> Optional[Dict]:
        if not self.file_path:
            return None

        unidades = set(self.unidades_colunas.values())

        is_3d = "m" in unidades  # posições 3D em metros
        is_emg = "V" in unidades  # EMG em Volts
        is_force = "N" in unidades  # Forças em Newtons

        types_found = []
        if is_3d:
            types_found.append("3D")
        if is_emg:
            types_found.append("EMG")
        if is_force:
            types_found.append("Force")

        type_str = " + ".join(types_found) if types_found else "Unknown Data"

        return {
            "format": "BTS TDF Binary",
            "type": type_str,
            "measure_unit": "",
            "sequences": (
                str(len(self.dataframe)) if self.dataframe is not None else "0"
            ),
        }

    def is_loaded(self) -> bool:
        return self.dataframe is not None

    def extrai_infos(self) -> Tuple:
        sucesso = self.open_tdf_file()

        if sucesso:
            df = self.get_dataframe()
            conteudo = self.get_file_info()
            cabecalho = self.get_header_info()
            return df, conteudo, cabecalho, self.unidades_colunas
        else:
            return None, None, None, None

    @staticmethod
    def _obter_unidades_tdf() -> Dict[str, str]:
        """Retorna o mapeamento de unidades convencionais do formato TDF.

        O formato TDF da BTS Bioengineering armazena dados nativamente em SI.
        A biblioteca basictdf NÃO expõe atributos de unidade explícitos —
        as unidades são convenção do formato binário.

        Returns:
            Dicionário com as chaves de grandeza e suas unidades SI.
        """
        return UNIDADES_TDF.copy()

    def _parse_tdf_file(self, file_path: str) -> Tuple[pd.DataFrame, Dict[str, str]]:
        from basictdf.tdfForcePlatformsData import ForcePlatformsDataBlock
        from basictdf import basictdf as _basictdf_mod

        dfs_to_merge = []
        unidades_colunas = {}  # {nome_coluna: unidade}

        # Unidades do formato TDF (SI)
        u = UNIDADES_TDF

        # A biblioteca basictdf requer o uso de context manager (with Tdf(...) as tdf:)
        # para que tdf.entries seja populado e o handler permaneça aberto durante
        # toda a sessão de leitura. Sem o "with", tdf.entries não existe e os
        # decoradores @provide_context_if_needed abrem/fecham o arquivo individualmente
        # a cada chamada de propriedade, impedindo leituras sequenciais corretas.
        with Tdf(file_path) as tdf:

            # 1. Processa dados 3D (Cinemática)
            if hasattr(tdf, "has_data3D") and tdf.has_data3D:
                data3D = tdf.data3D
                n_frames = data3D.nFrames
                frequency = data3D.frequency
                start_time = getattr(data3D, "startTime", 0.0)

                data_dict_3d = {
                    "time": [start_time + (i / frequency) for i in range(n_frames)]
                }

                un_pos = u["3d_posicao"]  # m
                for track in data3D.tracks:
                    label = track.label
                    col_x = f"{label}_x"
                    col_y = f"{label}_y"
                    col_z = f"{label}_z"
                    data_dict_3d[col_x] = track.X
                    data_dict_3d[col_y] = track.Y
                    data_dict_3d[col_z] = track.Z
                    unidades_colunas[col_x] = un_pos
                    unidades_colunas[col_y] = un_pos
                    unidades_colunas[col_z] = un_pos

                df_3d = pd.DataFrame(data_dict_3d)
                dfs_to_merge.append(df_3d)

            # 2. Processa Dados EMG (Eletromiografia)
            if hasattr(tdf, "has_emg") and tdf.has_emg:
                emg = tdf.emg
                n_samples = emg.nSamples
                frequency = emg.frequency
                start_time = getattr(emg, "startTime", 0.0)

                data_dict_emg = {
                    "time": [start_time + (i / frequency) for i in range(n_samples)]
                }

                un_emg = u["emg"]  # V
                for signal in emg:
                    label = signal.label
                    data_dict_emg[label] = signal.data
                    unidades_colunas[label] = un_emg

                df_emg = pd.DataFrame(data_dict_emg)
                dfs_to_merge.append(df_emg)

            # 3. Processa Dados da Plataforma de Força (Dinâmica)

            #    Formato processado (forceAndTorqueData, tipo 12)
            if hasattr(tdf, "has_force_and_torque") and tdf.has_force_and_torque:
                force_block = tdf.force_and_torque
                n_frames = force_block.nFrames
                frequency = force_block.frequency
                start_time = getattr(force_block, "startTime", 0.0)

                data_dict_force = {
                    "time": [start_time + (i / frequency) for i in range(n_frames)]
                }

                un_forca = u["forca"]  # N
                un_cop = u["cop"]  # m
                un_torque = u["torque"]  # N.m

                for channel, plat in enumerate(force_block.tracks):
                    col_fx = f"Plat{channel}_Fx"
                    col_fy = f"Plat{channel}_Fy"
                    col_fz = f"Plat{channel}_Fz"
                    data_dict_force[col_fx] = plat.force[:, 0]
                    data_dict_force[col_fy] = plat.force[:, 1]
                    data_dict_force[col_fz] = plat.force[:, 2]
                    unidades_colunas[col_fx] = un_forca
                    unidades_colunas[col_fy] = un_forca
                    unidades_colunas[col_fz] = un_forca

                    col_copx = f"Plat{channel}_CoPx"
                    col_copy = f"Plat{channel}_CoPy"
                    data_dict_force[col_copx] = plat.application_point[:, 0]
                    data_dict_force[col_copy] = plat.application_point[:, 1]
                    unidades_colunas[col_copx] = un_cop
                    unidades_colunas[col_copy] = un_cop

                    col_tz = f"Plat{channel}_Tz"
                    data_dict_force[col_tz] = plat.torque[:, 2]
                    unidades_colunas[col_tz] = un_torque

                df_force = pd.DataFrame(data_dict_force)
                dfs_to_merge.append(df_force)

            else:
                # Fallback: Formato bruto (forcePlatformsData, tipo 9)
                # Localiza a entrada forcePlatformsData no índice (TOC) e
                # constrói o bloco sob demanda, ainda dentro do contexto aberto.
                tipo_fp = _basictdf_mod.BlockType.forcePlatformsData
                fp_entry = next(
                    (e for e in tdf.entries if e.type == tipo_fp), None
                )

                if fp_entry is not None:
                    try:
                        tdf.handler.seek(fp_entry.offset, 0)
                        blk = ForcePlatformsDataBlock._build(
                            tdf.handler, fp_entry.format
                        )
                    except Exception:
                        blk = None

                    if (
                        blk is not None
                        and isinstance(blk, ForcePlatformsDataBlock)
                        and getattr(blk, "nBytes", 0) > 0
                    ):
                        # Atributos do ForcePlatformsDataBlock:
                        #   n_frames (não nFrames), start_time (não startTime)
                        n_frames = blk.n_frames
                        frequency = int(blk.frequency)
                        start_time = float(getattr(blk, "start_time", 0.0))

                        data_dict_force = {
                            "time": [
                                start_time + (i / frequency) for i in range(n_frames)
                            ]
                        }

                        un_forca = u["forca"]  # N
                        un_cop = u["cop"]  # m
                        un_torque = u["torque"]  # N.m

                        for channel, plat in enumerate(blk._platforms):
                            col_fx = f"Plat{channel}_Fx"
                            col_fy = f"Plat{channel}_Fy"
                            col_fz = f"Plat{channel}_Fz"
                            data_dict_force[col_fx] = plat.force[:, 0]
                            data_dict_force[col_fy] = plat.force[:, 1]
                            data_dict_force[col_fz] = plat.force[:, 2]
                            unidades_colunas[col_fx] = un_forca
                            unidades_colunas[col_fy] = un_forca
                            unidades_colunas[col_fz] = un_forca

                            col_copx = f"Plat{channel}_CoPx"
                            col_copy = f"Plat{channel}_CoPy"
                            data_dict_force[col_copx] = plat.application_point[:, 0]
                            data_dict_force[col_copy] = plat.application_point[:, 1]
                            unidades_colunas[col_copx] = un_cop
                            unidades_colunas[col_copy] = un_cop

                            col_tz = f"Plat{channel}_Tz"
                            # torque no ForcePlatformsDataBlock é array 1D (Mz)
                            data_dict_force[col_tz] = plat.torque
                            unidades_colunas[col_tz] = un_torque

                        df_force = pd.DataFrame(data_dict_force)
                        dfs_to_merge.append(df_force)

        # Unidades das colunas padrão
        unidades_colunas["time"] = "s"
        unidades_colunas["frame"] = "frames"

        # Verificação de segurança
        if not dfs_to_merge:
            raise ValueError(
                "O arquivo TDF não contém dados 3D, EMG ou de Plataforma de Força."
            )

        # Lógica de Merge Unificada
        if len(dfs_to_merge) == 1:
            final_df = dfs_to_merge[0]
        else:
            for df in dfs_to_merge:
                df["time_round"] = df["time"].round(4)

            final_df = dfs_to_merge[0]
            for i in range(1, len(dfs_to_merge)):
                final_df = pd.merge(
                    final_df,
                    dfs_to_merge[i],
                    on="time_round",
                    how="outer",
                    suffixes=("", "_dup"),
                )

                if "time_dup" in final_df.columns:
                    final_df["time"] = final_df["time"].fillna(final_df["time_dup"])
                    final_df = final_df.drop(columns=["time_dup"])

            final_df = final_df.drop(columns=["time_round"])

        # Limpeza e ordenação
        final_df = final_df.sort_values("time").reset_index(drop=True)
        final_df.insert(0, "frame", final_df.index)

        cols = list(final_df.columns)
        cols.remove("frame")
        cols.remove("time")
        final_df = final_df[["frame", "time"] + cols]

        return final_df, unidades_colunas
