"""
canvas_ipost.py
===============
QGraphicsScene interativo para cálculo do Índice Postural (IPost).

Hierarquia de objetos gráficos
--------------------------------
CanvasIPost (QGraphicsScene)
  ├── QGraphicsPixmapItem  — imagem de fundo
  ├── LinhaDePromo         — linha vermelha vertical, arrastável horizontalmente
  └── SegmentoMedicao × 4  — dK, dB, dL, dS
        ├── QGraphicsLineItem  — segmento de conexão
        ├── PontoAncora        — Ponto A, confinado à linha de prumo (desliza em Y)
        ├── PontoLivre         — Ponto B, arrastável livremente
        └── LabelFlutuante     — rótulo sobre Ponto B com nome e comprimento

Fórmula:
    IPost = (dK + dS) / (dB + dL)

Undo/Redo
---------
Padrão Memento com duas pilhas (_pilha_undo / _pilha_redo).
O estado é capturado no mouseRelease (não durante o drag).
Ao ativar o modo IPost, o estado inicial é automaticamente salvo.
Toda nova edição manual limpa a pilha redo.
"""

import math
from dataclasses import dataclass, field
from PyQt6.QtWidgets import (
    QGraphicsScene,
    QGraphicsLineItem,
    QGraphicsEllipseItem,
    QGraphicsTextItem,
    QGraphicsItem,
    QGraphicsRectItem,
)
from PyQt6.QtCore import Qt, QPointF, pyqtSignal, QObject
from PyQt6.QtGui import QPen, QColor, QBrush, QFont


# ---------------------------------------------------------------------------
# Constantes visuais
# ---------------------------------------------------------------------------
COR_PRUMO = QColor("#E53935")          # Vermelho
COR_SEGMENTO = QColor("#1E88E5")       # Azul
COR_PONTO_ANCORA = QColor("#34363614")   # Amarelo
COR_PONTO_LIVRE = QColor("#5F5F5F42")    # Verde
COR_LABEL_BG = QColor(30, 30, 30, 180)
COR_LABEL_TEXT = QColor("#FFFFFF")
RAIO_CENTRO = 2         # px, raio do ponto preto central
ESPESSURA_PRUMO = 2     # px
ESPESSURA_SEGMENTO = 2  # px
TOLERANCIA_CLIQUE_PRUMO = 12  # px, zona de clique para arrastar a linha
MAX_HISTORICO = 50       # limite de estados no histórico de undo


def _raio_tela() -> int:
    """
    Retorna o raio dos handles em *logical pixels de tela*, escalado pelo
    devicePixelRatio da tela primária.

    Em Qt 6 todas as coordenadas de widget/item já estão em logical pixels,
    de modo que o valor base (9 px) produz o mesmo tamanho físico em qualquer
    monitor.  A consulta ao devicePixelRatio serve como salvaguarda extra para
    ambientes onde a cadeia de escalonamento não seja totalmente automática
    (VMs, sessões de área de trabalho remota, Qt 5 legado).

    Resultado limitado a [8, 20] para evitar extremos em DPIs incomuns.
    """
    try:
        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        dpr = screen.devicePixelRatio() if screen is not None else 1.0
    except Exception:
        dpr = 1.0
    base = 6  # logical pixels em escala 1× (100 % DPI)
    return max(5, min(20, round(base * max(1.0, dpr))))



# ---------------------------------------------------------------------------
# EstadoIPost  (Memento)
# ---------------------------------------------------------------------------
@dataclass
class EstadoIPost:
    """
    Snapshot completo do estado dos marcadores do IPost.

    Atributos:
        x_prumo: posição X da linha de prumo.
        posicoes: dicionário nome_segmento → {xa, ya, xb, yb}.
    """
    x_prumo: float
    posicoes: dict = field(default_factory=dict)

    def copiar(self) -> "EstadoIPost":
        """Retorna uma cópia independente do estado."""
        return EstadoIPost(
            x_prumo=self.x_prumo,
            posicoes={nome: dict(coords) for nome, coords in self.posicoes.items()},
        )


# ---------------------------------------------------------------------------
# LabelFlutuante
# ---------------------------------------------------------------------------
class LabelFlutuante(QGraphicsRectItem):
    """
    Label com fundo semitransparente exibida sobre o Ponto B de cada segmento.
    Mostra o nome do segmento e seu comprimento atual em pixels.
    """

    def __init__(self, nome: str, parent: QGraphicsItem = None):
        super().__init__(parent)
        self._nome = nome

        # Fundo
        self.setBrush(QBrush(COR_LABEL_BG))
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setZValue(10)

        # Texto sobreposto ao fundo
        self._texto = QGraphicsTextItem(self)
        fonte = QFont("Segoe UI", 8, QFont.Weight.Bold)
        self._texto.setFont(fonte)
        self._texto.setDefaultTextColor(COR_LABEL_TEXT)
        self._texto.setPos(4, 2)

        self.atualizar(0.0)

    def atualizar(self, comprimento: float):
        """Atualiza o texto exibido e redimensiona o retângulo de fundo."""
        texto = f"{self._nome}: {comprimento:.1f} px"
        self._texto.setPlainText(texto)
        rect = self._texto.boundingRect()
        self.setRect(0, 0, rect.width() + 8, rect.height() + 4)


# ---------------------------------------------------------------------------
# PontoLivre  (Ponto B — arrastável livremente)
# ---------------------------------------------------------------------------
class PontoLivre(QGraphicsEllipseItem):
    """
    Handle circular arrastável livremente pelo canvas.

    Usa ``ItemIgnoresTransformations`` para manter tamanho visual constante
    na tela independente do nível de zoom aplicado à view.  Como essa flag é
    incompatível com ``ItemIsMovable``, o drag é implementado manualmente:
    os deltas são calculados em *coordenadas de cena* via ``scenePos()``,
    que é sempre correto mesmo com a flag ativa.

    O ``itemChange(ItemPositionChange)`` continua sendo disparado por
    ``ItemSendsGeometryChanges`` e recebe o valor em coordenadas de cena —
    mantendo toda a lógica de notificação do SegmentoMedicao intacta.
    """

    def __init__(self, x: float, y: float, segmento, parent: QGraphicsItem = None):
        r = _raio_tela()  # logical pixels de tela, DPI-aware
        super().__init__(-r, -r, 2 * r, 2 * r, parent)
        self._segmento = segmento
        self.setPos(x, y)
        self.setBrush(QBrush(COR_PONTO_LIVRE))
        self.setPen(QPen(QColor("#FFFFFF"), 1.5))
        self.setZValue(5)
        # ItemIgnoresTransformations → tamanho visual fixo em tela (zoom-invariant).
        # ItemIsMovable é OMITIDO intencionalmente (incompatível com o flag acima).
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)

        # Estado interno do drag manual
        self._arrastando: bool = False
        self._drag_start_scene: QPointF = QPointF()
        self._pos_inicial: QPointF = QPointF()

        # Ponto preto central (filho → herda o espaço local = pixels de tela)
        rc = RAIO_CENTRO
        self._centro = QGraphicsEllipseItem(-rc, -rc, 2 * rc, 2 * rc, self)
        self._centro.setBrush(QBrush(QColor("#000000")))
        self._centro.setPen(QPen(Qt.PenStyle.NoPen))
        self._centro.setZValue(6)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            # value está em coordenadas de cena — notifica o segmento
            if self._segmento is not None:
                self._segmento._on_ponto_livre_movido(value)
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        """Inicia o drag manual ao pressionar o botão esquerdo."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._arrastando = True
            self._drag_start_scene = event.scenePos()   # coordenadas de cena
            self._pos_inicial = self.pos()               # pos() em cena
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """
        Move o handle calculando o delta em coordenadas de cena.

        ``scenePos()`` retorna a posição correta em cena mesmo com
        ``ItemIgnoresTransformations`` ativo.
        """
        if self._arrastando:
            delta = event.scenePos() - self._drag_start_scene
            self.setPos(self._pos_inicial + delta)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """Encerra o drag e salva o estado no histórico de undo."""
        if self._arrastando and event.button() == Qt.MouseButton.LeftButton:
            self._arrastando = False
            if self._segmento is not None:
                self._segmento._cena._salvar_passo()
            event.accept()
        else:
            super().mouseReleaseEvent(event)


# ---------------------------------------------------------------------------
# PontoAncora  (Ponto A — desliza verticalmente sobre a linha de prumo)
# ---------------------------------------------------------------------------
class PontoAncora(QGraphicsEllipseItem):
    """
    Handle circular confinado à linha de prumo.

    Move-se apenas no eixo Y; o eixo X sempre acompanha a linha de prumo.
    Usa ``ItemIgnoresTransformations`` (tamanho visual fixo em tela) com
    drag manual, pelos mesmos motivos que ``PontoLivre``.

    O confinamento ao X de prumo é garantido pelo ``itemChange``: ao receber
    ``ItemPositionChange``, ele substitui o X proposto pelo ``_x_prumo``
    atual e retorna a posição corrigida — funcionamento idêntico ao original.
    """

    def __init__(self, x: float, y: float, segmento, parent: QGraphicsItem = None):
        r = _raio_tela()  # logical pixels de tela, DPI-aware
        super().__init__(-r, -r, 2 * r, 2 * r, parent)
        self._segmento = segmento
        self._x_prumo = x
        self.setPos(x, y)
        self.setBrush(QBrush(COR_PONTO_ANCORA))
        self.setPen(QPen(QColor("#FFFFFF"), 1.5))
        self.setZValue(5)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)

        # Estado interno do drag manual
        self._arrastando: bool = False
        self._drag_start_scene: QPointF = QPointF()
        self._pos_inicial_y: float = 0.0

        # Ponto preto central
        rc = RAIO_CENTRO
        self._centro = QGraphicsEllipseItem(-rc, -rc, 2 * rc, 2 * rc, self)
        self._centro.setBrush(QBrush(QColor("#000000")))
        self._centro.setPen(QPen(Qt.PenStyle.NoPen))
        self._centro.setZValue(6)

    def fixar_x(self, x: float):
        """Atualiza o X de prumo e reposiciona o ponto imediatamente."""
        self._x_prumo = x
        self.setPos(x, self.y())

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            # Força o X a permanecer na linha de prumo; value em coords de cena
            nova_pos = QPointF(self._x_prumo, value.y())
            if self._segmento is not None:
                self._segmento._on_ponto_ancora_movido(nova_pos)
            return nova_pos
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        """Inicia o drag manual restrito ao eixo Y."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._arrastando = True
            self._drag_start_scene = event.scenePos()
            self._pos_inicial_y = self.pos().y()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """
        Move o handle apenas no eixo Y.

        O delta Y é calculado em coordenadas de cena; o X de prumo é sempre
        mantido pelo ``itemChange`` ao aplicar o ``setPos``.
        """
        if self._arrastando:
            delta_y = event.scenePos().y() - self._drag_start_scene.y()
            # setPos dispara itemChange que garante x = _x_prumo
            self.setPos(self._x_prumo, self._pos_inicial_y + delta_y)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """Encerra o drag e salva o estado no histórico de undo."""
        if self._arrastando and event.button() == Qt.MouseButton.LeftButton:
            self._arrastando = False
            if self._segmento is not None:
                self._segmento._cena._salvar_passo()
            event.accept()
        else:
            super().mouseReleaseEvent(event)


# ---------------------------------------------------------------------------
# SegmentoMedicao
# ---------------------------------------------------------------------------
class SegmentoMedicao:
    """
    Agrupamento lógico de um segmento de medição anatômica.

    Contém:
    - Uma linha gráfica conectando Ponto A e Ponto B.
    - Um PontoAncora (A) sobre a linha de prumo.
    - Um PontoLivre (B) arrastável livremente.
    - Uma LabelFlutuante sobre o Ponto B.

    O comprimento é calculado como a distância euclidiana entre A e B.
    """

    def __init__(
        self,
        cena: "CanvasIPost",
        nome: str,
        x_prumo: float,
        y_ancora: float,
        x_livre: float,
        y_livre: float,
    ):
        self._cena = cena
        self._nome = nome
        self._comprimento = 0.0

        # Linha de conexão A–B
        self._linha = QGraphicsLineItem()
        pen = QPen(COR_SEGMENTO, ESPESSURA_SEGMENTO)
        pen.setStyle(Qt.PenStyle.DashLine)
        self._linha.setPen(pen)
        self._linha.setZValue(2)
        cena.addItem(self._linha)

        # Ponto A (âncora na linha de prumo)
        self._ponto_a = PontoAncora(x_prumo, y_ancora, self)
        cena.addItem(self._ponto_a)

        # Ponto B (livre)
        self._ponto_b = PontoLivre(x_livre, y_livre, self)
        cena.addItem(self._ponto_b)

        # Label flutuante sobre Ponto B
        self._label = LabelFlutuante(nome)
        cena.addItem(self._label)

        self._atualizar_visual()

    # ------------------------------------------------------------------
    # Propriedades
    # ------------------------------------------------------------------

    @property
    def comprimento(self) -> float:
        return self._comprimento

    @property
    def nome(self) -> str:
        return self._nome

    # ------------------------------------------------------------------
    # Snapshot de posições para o histórico
    # ------------------------------------------------------------------

    def snapshot(self) -> dict:
        """Retorna um dicionário com as posições atuais de A e B."""
        pa = self._ponto_a.pos()
        pb = self._ponto_b.pos()
        return {"xa": pa.x(), "ya": pa.y(), "xb": pb.x(), "yb": pb.y()}

    def restaurar(self, coords: dict):
        """
        Restaura as posições de A e B a partir de um dicionário de coordenadas.
        Atualiza o visual sem disparar novo passo no histórico.
        """
        # Bloqueia sinais de geometria temporariamente durante a restauração
        self._ponto_a.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, False)
        self._ponto_b.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, False)

        self._ponto_a._x_prumo = coords["xa"]
        self._ponto_a.setPos(coords["xa"], coords["ya"])
        self._ponto_b.setPos(coords["xb"], coords["yb"])

        self._ponto_a.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self._ponto_b.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)

        self._atualizar_visual()

    # ------------------------------------------------------------------
    # Callbacks dos pontos
    # ------------------------------------------------------------------

    def _on_ponto_livre_movido(self, nova_pos: QPointF):
        """Chamado pelo PontoLivre ao se mover (antes de aplicar a posição)."""
        pa = self._ponto_a.pos()
        pb = nova_pos
        self._comprimento = math.hypot(pb.x() - pa.x(), pb.y() - pa.y())
        self._label.atualizar(self._comprimento)
        # Atualiza a linha usando a nova posição antes do itemChange ser aplicado
        self._linha.setLine(pa.x(), pa.y(), pb.x(), pb.y())
        # Posiciona a label com pequeno offset acima/direita do Ponto B
        self._label.setPos(pb.x() + _raio_tela() + 4, pb.y() - self._label.rect().height() - 4)
        # Notifica a cena
        self._cena._on_medida_alterada()

    def _on_ponto_ancora_movido(self, nova_pos: QPointF):
        """Chamado pelo PontoAncora ao se mover (antes de aplicar a posição)."""
        pa = nova_pos
        pb = self._ponto_b.pos()
        self._comprimento = math.hypot(pb.x() - pa.x(), pb.y() - pa.y())
        self._label.atualizar(self._comprimento)
        self._linha.setLine(pa.x(), pa.y(), pb.x(), pb.y())
        self._cena._on_medida_alterada()

    # ------------------------------------------------------------------
    # Atualização da linha de prumo
    # ------------------------------------------------------------------

    def atualizar_x_prumo(self, x: float):
        """Chamado pela LinhaDePromo ao ser arrastada. Move Ponto A horizontalmente."""
        self._ponto_a.fixar_x(x)
        # Recalcula com a nova posição de A
        pa = self._ponto_a.pos()
        pb = self._ponto_b.pos()
        self._comprimento = math.hypot(pb.x() - pa.x(), pb.y() - pa.y())
        self._label.atualizar(self._comprimento)
        self._linha.setLine(pa.x(), pa.y(), pb.x(), pb.y())
        self._cena._on_medida_alterada()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _atualizar_visual(self):
        """Posiciona todos os elementos gráficos de acordo com as posições atuais."""
        pa = self._ponto_a.pos()
        pb = self._ponto_b.pos()
        self._comprimento = math.hypot(pb.x() - pa.x(), pb.y() - pa.y())
        self._label.atualizar(self._comprimento)
        self._linha.setLine(pa.x(), pa.y(), pb.x(), pb.y())
        self._label.setPos(pb.x() + _raio_tela() + 4, pb.y() - self._label.rect().height() - 4)

    def remover_da_cena(self):
        """Remove todos os itens gráficos da cena."""
        for item in (self._linha, self._ponto_a, self._ponto_b, self._label):
            self._cena.removeItem(item)


# ---------------------------------------------------------------------------
# LinhaDePromo
# ---------------------------------------------------------------------------
class LinhaDePromo(QGraphicsLineItem):
    """
    Linha vermelha vertical que atravessa a imagem de topo a base.
    Pode ser arrastada horizontalmente pelo usuário.
    A cena gerencia o drag diretamente via mouseMoveEvent para maior controle.
    """

    def __init__(self, x: float, altura: float):
        super().__init__(x, 0, x, altura)
        pen = QPen(COR_PRUMO, ESPESSURA_PRUMO)
        self.setPen(pen)
        self.setZValue(3)
        self._altura = altura
        self._x = x

    @property
    def x_atual(self) -> float:
        return self._x

    def mover_para(self, x: float):
        """Reposiciona a linha verticalmente em X."""
        self._x = x
        self.setLine(x, 0, x, self._altura)

    def atualizar_altura(self, altura: float):
        """Atualiza a altura da linha quando uma nova imagem for carregada."""
        self._altura = altura
        self.setLine(self._x, 0, self._x, altura)


# ---------------------------------------------------------------------------
# CanvasIPost  (QGraphicsScene principal)
# ---------------------------------------------------------------------------
class _Sinais(QObject):
    """QObject auxiliar para hospedar sinais PyQt (QGraphicsScene não é QObject direto)."""
    medidas_atualizadas = pyqtSignal(dict)
    historico_alterado = pyqtSignal(bool, bool)  # (pode_undo, pode_redo)


class CanvasIPost(QGraphicsScene):
    """
    Cena principal do Índice Postural.

    Contém:
    - Imagem de fundo carregável via `carregar_imagem(caminho)`.
    - Uma linha de prumo vermelha.
    - Quatro segmentos de medição: dK, dB, dL, dS.

    Emite `sinais.medidas_atualizadas` com dicionário
    {'dK': float, 'dB': float, 'dL': float, 'dS': float}
    a cada alteração.

    Emite `sinais.historico_alterado(pode_undo: bool, pode_redo: bool)`
    sempre que as pilhas de undo/redo mudarem.

    Undo/Redo:
        - `undo()`: desfaz o último passo.
        - `redo()`: refaz o último passo desfeito.
        Estado é salvo automaticamente no mouseRelease e ao ativar o modo.
    """

    # Nomes dos segmentos na ordem em que aparecem no canvas
    NOMES_SEGMENTOS = ["dK", "dB", "dL", "dS"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sinais = _Sinais()

        self._imagem_item = None
        self._largura = 800
        self._altura = 600
        self._linha_prumo: LinhaDePromo | None = None
        self._segmentos: list[SegmentoMedicao] = []
        self._arrastando_prumo = False
        self._modo_ativo = False

        # Histórico de undo/redo
        self._pilha_undo: list[EstadoIPost] = []
        self._pilha_redo: list[EstadoIPost] = []
        # Flag para suprimir salvamento durante restauração
        self._restaurando = False

        # Fundo cinza escuro enquanto nenhuma imagem estiver carregada
        self.setBackgroundBrush(QBrush(QColor("#2B2B2B")))

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def carregar_imagem(self, caminho: str):
        """Carrega uma imagem PNG/JPG e redimensiona a cena."""
        from PyQt6.QtGui import QPixmap

        pixmap = QPixmap(caminho)
        if pixmap.isNull():
            return False

        # Remove a imagem anterior se existir
        if self._imagem_item is not None:
            self.removeItem(self._imagem_item)

        self._imagem_item = self.addPixmap(pixmap)
        self._imagem_item.setZValue(0)
        self._largura = pixmap.width()
        self._altura = pixmap.height()
        self.setSceneRect(0, 0, self._largura, self._altura)

        if self._modo_ativo:
            self._atualizar_geometria_modo()

        return True

    def ativar_modo_ipost(self):
        """Ativa o modo de edição anatômica: cria linha de prumo e segmentos."""
        if self._modo_ativo:
            return
        self._modo_ativo = True
        self._criar_elementos()
        # Salva o estado inicial como primeiro passo do histórico
        self._salvar_passo()

    def desativar_modo_ipost(self):
        """Remove a linha de prumo e os segmentos da cena."""
        if not self._modo_ativo:
            return
        self._modo_ativo = False
        self._limpar_elementos()
        # Limpa o histórico ao desativar
        self._pilha_undo.clear()
        self._pilha_redo.clear()
        self.sinais.historico_alterado.emit(False, False)

    def get_medidas(self) -> dict:
        """Retorna o dicionário atual com os comprimentos dos 4 segmentos."""
        return {
            seg.nome: seg.comprimento
            for seg in self._segmentos
        }

    # ------------------------------------------------------------------
    # Undo / Redo — API pública
    # ------------------------------------------------------------------

    def capturar_estado(self) -> EstadoIPost:
        """Cria e retorna um snapshot do estado atual dos marcadores."""
        if self._linha_prumo is None:
            return EstadoIPost(x_prumo=self._largura / 2)
        return EstadoIPost(
            x_prumo=self._linha_prumo.x_atual,
            posicoes={seg.nome: seg.snapshot() for seg in self._segmentos},
        )

    def aplicar_estado(self, estado: EstadoIPost):
        """
        Restaura as posições dos marcadores a partir de um EstadoIPost.
        Não gera novo passo no histórico.
        """
        if self._linha_prumo is None or not self._segmentos:
            return

        self._restaurando = True
        try:
            # Restaura a linha de prumo
            self._linha_prumo.mover_para(estado.x_prumo)

            # Restaura cada segmento
            for seg in self._segmentos:
                if seg.nome in estado.posicoes:
                    coords = estado.posicoes[seg.nome]
                    seg.restaurar(coords)

            # Força repaint e emite medidas
            self.update()
            self._on_medida_alterada()
        finally:
            self._restaurando = False

    def undo(self):
        """
        Desfaz o último passo:
        - Remove o topo da pilha undo
        - Empurra o estado atual na pilha redo
        - Aplica o estado anterior
        """
        if not self._pilha_undo:
            return
        estado_anterior = self._pilha_undo.pop()
        estado_atual = self.capturar_estado()
        self._pilha_redo.append(estado_atual)
        self.aplicar_estado(estado_anterior)
        self.sinais.historico_alterado.emit(
            bool(self._pilha_undo), bool(self._pilha_redo)
        )

    def redo(self):
        """
        Refaz o último passo desfeito:
        - Remove o topo da pilha redo
        - Empurra o estado atual na pilha undo
        - Aplica o estado redo
        """
        if not self._pilha_redo:
            return
        estado_redo = self._pilha_redo.pop()
        estado_atual = self.capturar_estado()
        self._pilha_undo.append(estado_atual)
        self.aplicar_estado(estado_redo)
        self.sinais.historico_alterado.emit(
            bool(self._pilha_undo), bool(self._pilha_redo)
        )

    # ------------------------------------------------------------------
    # Lógica interna do histórico
    # ------------------------------------------------------------------

    def _salvar_passo(self):
        """
        Captura o estado atual e empurra na pilha undo.
        Limpa a pilha redo (nova edição invalida o futuro).
        Limita o tamanho do histórico a MAX_HISTORICO entradas.
        Não age durante uma restauração.
        """
        if self._restaurando or not self._modo_ativo:
            return

        estado = self.capturar_estado()
        self._pilha_undo.append(estado)
        self._pilha_redo.clear()

        # Limita o tamanho do histórico
        if len(self._pilha_undo) > MAX_HISTORICO:
            self._pilha_undo.pop(0)

        self.sinais.historico_alterado.emit(
            bool(self._pilha_undo), bool(self._pilha_redo)
        )

    # ------------------------------------------------------------------
    # Criação e remoção de elementos
    # ------------------------------------------------------------------

    def _criar_elementos(self):
        """Cria a linha de prumo e os 4 segmentos numa posição inicial razoável."""
        cx = self._largura / 2
        cy = self._altura / 2

        # Linha de prumo
        self._linha_prumo = LinhaDePromo(cx, self._altura)
        self.addItem(self._linha_prumo)

        # Posições iniciais dos segmentos (distribuídas verticalmente)
        # Ponto A na linha de prumo; Ponto B deslocado 120px à direita
        offsets_y = [cy * 0.35, cy * 0.55, cy * 0.75, cy * 0.90]
        deslocamento_b = 120  # px inicial para o Ponto B

        for i, nome in enumerate(self.NOMES_SEGMENTOS):
            y = offsets_y[i]
            seg = SegmentoMedicao(
                cena=self,
                nome=nome,
                x_prumo=cx,
                y_ancora=y,
                x_livre=cx + deslocamento_b,
                y_livre=y,
            )
            self._segmentos.append(seg)

    def _limpar_elementos(self):
        """Remove todos os elementos de medição da cena."""
        if self._linha_prumo is not None:
            self.removeItem(self._linha_prumo)
            self._linha_prumo = None

        for seg in self._segmentos:
            seg.remover_da_cena()
        self._segmentos.clear()

    def _atualizar_geometria_modo(self):
        """Recria os elementos com a nova geometria da imagem."""
        self._limpar_elementos()
        self._criar_elementos()

    # ------------------------------------------------------------------
    # Callback interno — chamado pelos segmentos
    # ------------------------------------------------------------------

    def _on_medida_alterada(self):
        """Emite o sinal com as medidas atualizadas."""
        self.sinais.medidas_atualizadas.emit(self.get_medidas())

    # ------------------------------------------------------------------
    # Interação com a linha de prumo (drag horizontal)
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        """Inicia o drag da linha de prumo se o clique for próximo a ela."""
        if (
            self._modo_ativo
            and self._linha_prumo is not None
            and event.button() == Qt.MouseButton.LeftButton
        ):
            pos = event.scenePos()
            dist = abs(pos.x() - self._linha_prumo.x_atual)
            if dist <= TOLERANCIA_CLIQUE_PRUMO:
                # Verifica se o clique não foi em cima de um ponto interativo
                itens = self.items(pos)
                clicou_ponto = any(
                    isinstance(it, (PontoLivre, PontoAncora)) for it in itens
                )
                if not clicou_ponto:
                    self._arrastando_prumo = True
                    event.accept()
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Arrasta a linha de prumo e atualiza todos os Pontos A."""
        if self._arrastando_prumo and self._linha_prumo is not None:
            x = event.scenePos().x()
            # Confina ao interior da imagem
            x = max(0, min(x, self._largura))
            self._linha_prumo.mover_para(x)
            for seg in self._segmentos:
                seg.atualizar_x_prumo(x)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """Encerra o drag da linha de prumo e salva o estado no histórico."""
        if self._arrastando_prumo:
            self._arrastando_prumo = False
            event.accept()
            # Salva estado ao soltar a linha de prumo
            self._salvar_passo()
            return
        super().mouseReleaseEvent(event)
