"""
janela_ipost.py
================
Janela principal da ferramenta de Índice Postural (IPost).

Layout:
  ┌──────────────────────────────────┬──────────────────────┐
  │   QGraphicsView (canvas)         │  Painel Lateral       │
  │                                  │  ─────────────────    │
  │   [Imagem com linha de prumo     │  dK = 120.0 px        │
  │    e 4 segmentos interativos]    │  dS =  95.0 px        │
  │                                  │  dB = 110.0 px        │
  │                                  │  dL =  85.0 px        │
  │                                  │  ─────────────────    │
  │                                  │  IPost = 1.023        │
  └──────────────────────────────────┴──────────────────────┘

Interação com o canvas:
  - Botão esquerdo: arrasta a linha de prumo e os marcadores.
  - Scroll do mouse: zoom in/out centrado no cursor.
  - Botão do meio (ou direito): panning (arraste da visualização).
  - Botão "Reset Zoom": retorna ao enquadramento fitInView.

Uso:
    janela = JanelaIndicePostural(parent=main_window)
    janela.show()
"""

from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QGraphicsView,
    QGroupBox,
    QPushButton,
    QFileDialog,
    QSizePolicy,
    QFrame,
    QMenuBar,
    QWidget,
)
from PyQt6.QtCore import Qt, QSize, QPoint, QRectF
from PyQt6.QtGui import QAction, QFont, QColor, QKeySequence, QShortcut, QPainter, QImage

from ui.indice_postural.canvas_ipost import CanvasIPost


# ---------------------------------------------------------------------------
# Constantes de zoom
# ---------------------------------------------------------------------------
_FATOR_ZOOM = 1.15   # 15% por tick do scroll
_ZOOM_MAX = 20.0     # escala máxima (×20 da original)
_ZOOM_MIN = 0.05     # escala mínima (×0.05 da original)


# ---------------------------------------------------------------------------
# ViewIPost — QGraphicsView com zoom e panning
# ---------------------------------------------------------------------------
class ViewIPost(QGraphicsView):
    """
    QGraphicsView customizado para o canvas do Índice Postural.

    Implementa:
    - **Zoom com scroll do mouse**: centrado na posição do cursor
      (AnchorUnderMouse), com limites de escala configuráveis.
    - **Panning**: ativado pelo botão do meio **ou** pelo botão direito.
      O arraste move a cena por delta de pixels no viewport.

    A lógica de transformação é totalmente delegada ao QTransform nativo
    da QGraphicsView, de modo que os itens na QGraphicsScene continuam
    operando em coordenadas de cena intactas — sem perda de alinhamento
    entre a imagem e os marcadores.

    Atributos:
        zoom_ativo (bool): True quando o usuário já aplicou algum zoom
            manual (usado pela janela para suprimir o fitInView automático).
    """

    def __init__(self, cena: CanvasIPost, parent=None):
        super().__init__(cena, parent)
        self.zoom_ativo: bool = False

        # Âncora padrão: será sobrescrita em cada wheelEvent
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)

        # Estado interno de panning
        self._panning: bool = False
        self._pan_inicio: QPoint = QPoint()

    # ------------------------------------------------------------------
    # Zoom — scroll do mouse
    # ------------------------------------------------------------------

    def wheelEvent(self, event):
        """
        Zoom in/out centrado na posição do cursor.

        Matemática:
            fator = FATOR_ZOOM        se delta > 0 (scroll up  → aproximar)
            fator = 1 / FATOR_ZOOM   se delta < 0 (scroll down → afastar)

        O QGraphicsView aplica internamente:
            nova_transformação = scale(fator, fator) × transformação_atual

        Com AnchorUnderMouse ativo, a view ajusta automaticamente a
        translação para manter o ponto sob o cursor fixo na tela.
        """
        delta = event.angleDelta().y()
        if delta == 0:
            return

        # Determina o fator e verifica os limites
        if delta > 0:
            fator = _FATOR_ZOOM
            if self.transform().m11() >= _ZOOM_MAX:
                return
        else:
            fator = 1.0 / _FATOR_ZOOM
            if self.transform().m11() <= _ZOOM_MIN:
                return

        # Garante âncora no cursor para o zoom focal
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.scale(fator, fator)

        self.zoom_ativo = True
        event.accept()

    # ------------------------------------------------------------------
    # Panning — botão do meio ou direito
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        """Inicia o panning ao pressionar o botão do meio ou direito."""
        if event.button() in (
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.RightButton,
        ):
            self._panning = True
            self._pan_inicio = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """
        Executa o panning quando ativo.

        Matemática:
            delta = posição_atual − posição_início
            scrollbar_h -= delta.x()
            scrollbar_v -= delta.y()

        O sinal negativo converte o movimento do mouse (viewport)
        em deslocamento inverso da barra de rolagem, produzindo o
        comportamento intuitivo de "arrastar a cena".
        """
        if self._panning:
            pos_atual = event.position().toPoint()
            delta = pos_atual - self._pan_inicio
            self._pan_inicio = pos_atual

            h_bar = self.horizontalScrollBar()
            v_bar = self.verticalScrollBar()
            h_bar.setValue(h_bar.value() - delta.x())
            v_bar.setValue(v_bar.value() - delta.y())

            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """Encerra o panning ao soltar o botão."""
        if self._panning and event.button() in (
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.RightButton,
        ):
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------------
    # Reset público
    # ------------------------------------------------------------------

    def reset_zoom(self, scene_rect):
        """
        Redefine a transformação para o enquadramento inicial (fitInView).
        Também marca zoom_ativo = False para reabilitar o ajuste automático.
        """
        self.resetTransform()
        self.fitInView(scene_rect, Qt.AspectRatioMode.KeepAspectRatio)
        self.zoom_ativo = False


# ---------------------------------------------------------------------------
# JanelaIndicePostural
# ---------------------------------------------------------------------------
class JanelaIndicePostural(QDialog):
    """
    Janela completa de análise de Índice Postural.

    Contém:
    - Uma barra de menu interna (Arquivo → Abrir Imagem).
    - Um ViewIPost mostrando o CanvasIPost (com zoom e panning).
    - Um painel lateral com os valores dK, dB, dL, dS e IPost em tempo real.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Índice Postural (IPost)")
        self.setMinimumSize(1050, 680)
        self.resize(1200, 750)
        self.setWindowFlag(Qt.WindowType.Window, True)

        # Deixa a janela ser redimensionada (sobrepõe PadraoDialog se necessário)
        self.setSizeGripEnabled(True)

        # Guarda o último valor calculado do IPost (usado na exportação)
        self._ipost_valor: float | None = None

        self._construir_ui()
        self._conectar_sinais()

    # ------------------------------------------------------------------
    # Construção da UI
    # ------------------------------------------------------------------

    def _construir_ui(self):
        layout_raiz = QVBoxLayout(self)
        layout_raiz.setContentsMargins(0, 0, 0, 0)
        layout_raiz.setSpacing(0)

        # ── Barra de menu interna ──────────────────────────────────────
        self._menu_bar = QMenuBar(self)
        menu_arquivo = self._menu_bar.addMenu("Arquivo")

        self._acao_abrir = QAction("Abrir Imagem (PNG / JPG)…", self)
        self._acao_abrir.setShortcut("Ctrl+O")
        menu_arquivo.addAction(self._acao_abrir)

        menu_operacoes = self._menu_bar.addMenu("Operações")
        self._acao_ativar = QAction("Ativar Índice Postural", self)
        self._acao_ativar.setCheckable(True)
        menu_operacoes.addAction(self._acao_ativar)

        menu_operacoes.addSeparator()

        self._acao_undo = QAction("⟲  Desfazer", self)
        self._acao_undo.setShortcut("Ctrl+Z")
        self._acao_undo.setEnabled(False)
        menu_operacoes.addAction(self._acao_undo)

        self._acao_redo = QAction("⟳  Refazer", self)
        self._acao_redo.setShortcut("Ctrl+Y")
        self._acao_redo.setEnabled(False)
        menu_operacoes.addAction(self._acao_redo)


        layout_raiz.setMenuBar(self._menu_bar)

        # ── Área principal (canvas + painel lateral) ───────────────────
        widget_corpo = QWidget()
        layout_corpo = QHBoxLayout(widget_corpo)
        layout_corpo.setContentsMargins(6, 6, 6, 6)
        layout_corpo.setSpacing(8)

        # Canvas + View customizada
        self._cena = CanvasIPost()
        self._view = ViewIPost(self._cena)
        self._view.setRenderHint(self._view.renderHints().__class__.Antialiasing)
        self._view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        layout_corpo.addWidget(self._view, stretch=4)

        # Painel lateral
        painel = self._construir_painel_lateral()
        layout_corpo.addWidget(painel, stretch=1)

        layout_raiz.addWidget(widget_corpo)

    def _construir_painel_lateral(self) -> QWidget:
        """Monta o painel direito com os valores dos segmentos e o IPost."""
        painel = QGroupBox("Medições")
        painel.setFixedWidth(220)
        layout = QVBoxLayout(painel)
        layout.setSpacing(10)

        fonte_valor = QFont("Consolas", 11)
        fonte_titulo = QFont("Segoe UI", 9)
        fonte_titulo.setBold(True)
        fonte_ipost = QFont("Segoe UI", 14)
        fonte_ipost.setBold(True)

        # Título segmentos
        lbl_titulo = QLabel("Comprimentos (px)")
        lbl_titulo.setFont(fonte_titulo)
        lbl_titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_titulo)

        # Labels individuais por segmento
        self._labels_segmentos: dict[str, QLabel] = {}
        cores = {"dK": "#1565C0", "dS": "#558B2F", "dB": "#E65100", "dL": "#6A1B9A"}
        for nome in ["dK", "dS", "dB", "dL"]:
            lbl = QLabel(f"  {nome}  =   0.0 px")
            lbl.setFont(fonte_valor)
            lbl.setStyleSheet(
                f"color: {cores[nome]}; padding: 2px 4px;"
                "border: 1px solid #CCC; border-radius: 4px; background: #F5F5F5;"
            )
            layout.addWidget(lbl)
            self._labels_segmentos[nome] = lbl

        # Separador
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep)

        # Fórmula IPost
        lbl_formula = QLabel("IPost = (dK + dS)\n         ────────────\n         (dB + dL)")
        lbl_formula.setFont(QFont("Consolas", 8))
        lbl_formula.setStyleSheet("color: #555; padding: 2px;")
        lbl_formula.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_formula)

        self._label_ipost = QLabel("IPost = —")
        self._label_ipost.setFont(fonte_ipost)
        self._label_ipost.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label_ipost.setStyleSheet(
            "color: #B71C1C; padding: 8px;"
            "border: 2px solid #B71C1C; border-radius: 6px;"
            "background: #FFF8F8;"
        )
        layout.addWidget(self._label_ipost)

        # Separador
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep2)

        # Botão abrir imagem (atalho conveniente)
        self._btn_abrir = QPushButton("📂  Abrir Imagem")
        self._btn_abrir.setToolTip("Abrir imagem PNG ou JPG (Ctrl+O)")
        layout.addWidget(self._btn_abrir)

        # Botão ativar/desativar modo
        self._btn_ativar = QPushButton("▶  Ativar IPost")
        self._btn_ativar.setCheckable(True)
        self._btn_ativar.setToolTip("Ativa/desativa a linha de prumo e os segmentos")
        layout.addWidget(self._btn_ativar)

        # Botão reset zoom
        self._btn_reset_zoom = QPushButton("🔍  Reset Zoom")
        self._btn_reset_zoom.setToolTip(
            "Retorna o zoom ao enquadramento inicial (fitInView)"
        )
        layout.addWidget(self._btn_reset_zoom)

        # Separador
        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.HLine)
        sep3.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep3)

        # Botões Desfazer / Refazer
        self._btn_undo = QPushButton("⟲  Desfazer")
        self._btn_undo.setToolTip("Desfazer última ação (Ctrl+Z)")
        self._btn_undo.setEnabled(False)
        self._btn_undo.setStyleSheet(
            "QPushButton { color: #000000; background: #E3F2FD; border: 1px solid #90CAF9; border-radius: 4px; padding: 4px; }"
            "QPushButton:hover { color: #000000; background: #BBDEFB; }"
            "QPushButton:disabled { color: #BDBDBD; background: #F5F5F5; border-color: #E0E0E0; }"
        )
        layout.addWidget(self._btn_undo)

        self._btn_redo = QPushButton("⟳  Refazer")
        self._btn_redo.setToolTip("Refazer última ação desfeita (Ctrl+Y)")
        self._btn_redo.setEnabled(False)
        self._btn_redo.setStyleSheet(
            "QPushButton { color: #000000; background: #E8F5E9; border: 1px solid #A5D6A7; border-radius: 4px; padding: 4px; }"
            "QPushButton:hover { color: #000000; background: #C8E6C9; }"
            "QPushButton:disabled { color: #BDBDBD; background: #F5F5F5; border-color: #E0E0E0; }"
        )
        layout.addWidget(self._btn_redo)

        # Separador antes da exportação
        sep4 = QFrame()
        sep4.setFrameShape(QFrame.Shape.HLine)
        sep4.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep4)

        # Botão exportar imagem
        self._btn_exportar = QPushButton("📷  Exportar Imagem")
        self._btn_exportar.setToolTip(
            "Salva o canvas como PNG com o valor do IPost inscrito no canto superior direito"
        )
        self._btn_exportar.setStyleSheet(
            "QPushButton { color: #FFFFFF; background: #2E7D32; border: 1px solid #1B5E20;"
            " border-radius: 4px; padding: 6px; font-weight: bold; }"
            "QPushButton:hover { background: #388E3C; }"
            "QPushButton:disabled { color: #BDBDBD; background: #F5F5F5; border-color: #E0E0E0; }"
        )
        layout.addWidget(self._btn_exportar)

        layout.addStretch()

        # Nota de rodapé com instruções de navegação
        nota = QLabel(
            "🖱 Esq: arraste prumo/pontos\n"
            "🖱 Scroll: zoom (centrado)\n"
            "🖱 Meio/Dir: panning"
        )
        nota.setFont(QFont("Segoe UI", 8))
        nota.setStyleSheet("color: #888;")
        nota.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nota.setWordWrap(True)
        layout.addWidget(nota)

        return painel

    # ------------------------------------------------------------------
    # Conexão de sinais
    # ------------------------------------------------------------------

    def _conectar_sinais(self):
        self._acao_abrir.triggered.connect(self._abrir_imagem)
        self._btn_abrir.clicked.connect(self._abrir_imagem)

        self._acao_ativar.toggled.connect(self._toggle_modo_ipost)
        self._btn_ativar.toggled.connect(self._toggle_modo_ipost)

        # Sincroniza os dois controles (menu e botão)
        self._acao_ativar.toggled.connect(
            lambda estado: self._btn_ativar.setChecked(estado)
        )
        self._btn_ativar.toggled.connect(
            lambda estado: self._acao_ativar.setChecked(estado)
        )

        # Sinal da cena com as medidas atualizadas
        self._cena.sinais.medidas_atualizadas.connect(self._atualizar_painel)

        # Sinal do histórico (habilitar/desabilitar botões de undo/redo)
        self._cena.sinais.historico_alterado.connect(self._atualizar_estado_undo_redo)

        # Botões Desfazer / Refazer
        self._btn_undo.clicked.connect(self._cena.undo)
        self._btn_redo.clicked.connect(self._cena.redo)

        # Ações de menu Desfazer / Refazer
        self._acao_undo.triggered.connect(self._cena.undo)
        self._acao_redo.triggered.connect(self._cena.redo)

        # Atalhos de teclado: Ctrl+Z e Ctrl+Y / Ctrl+Shift+Z
        sc_undo = QShortcut(QKeySequence("Ctrl+Z"), self)
        sc_undo.activated.connect(self._cena.undo)

        sc_redo_y = QShortcut(QKeySequence("Ctrl+Y"), self)
        sc_redo_y.activated.connect(self._cena.redo)

        sc_redo_shift_z = QShortcut(QKeySequence("Ctrl+Shift+Z"), self)
        sc_redo_shift_z.activated.connect(self._cena.redo)

        # Reset zoom
        self._btn_reset_zoom.clicked.connect(self._reset_zoom)

        # Exportar imagem
        self._btn_exportar.clicked.connect(self._exportar_imagem)


    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _abrir_imagem(self):
        """Abre diálogo para selecionar uma imagem e carrega no canvas."""
        caminho, _ = QFileDialog.getOpenFileName(
            self,
            "Abrir Imagem",
            "",
            "Imagens (*.png *.jpg *.jpeg *.bmp *.tiff *.webp);;Todos os arquivos (*)",
        )
        if caminho:
            sucesso = self._cena.carregar_imagem(caminho)
            if sucesso:
                # Ajusta a view para mostrar toda a imagem e reseta o zoom
                self._view.reset_zoom(self._cena.sceneRect())
                # Ativa o modo automaticamente se ainda não estiver ativo
                if not self._btn_ativar.isChecked():
                    self._btn_ativar.setChecked(True)

    def _toggle_modo_ipost(self, ativado: bool):
        """Ativa ou desativa o modo de edição anatômica."""
        if ativado:
            self._cena.ativar_modo_ipost()
            self._btn_ativar.setText("⏹  Desativar IPost")
        else:
            self._cena.desativar_modo_ipost()
            self._btn_ativar.setText("▶  Ativar IPost")
            # Limpa o painel
            self._resetar_painel()

    def _atualizar_estado_undo_redo(self, pode_undo: bool, pode_redo: bool):
        """
        Slot conectado ao sinal `historico_alterado` da cena.
        Habilita ou desabilita os botões e ações de Desfazer/Refazer.
        """
        self._btn_undo.setEnabled(pode_undo)
        self._btn_redo.setEnabled(pode_redo)
        self._acao_undo.setEnabled(pode_undo)
        self._acao_redo.setEnabled(pode_redo)


    def _reset_zoom(self):
        """Slot do botão Reset Zoom: volta ao enquadramento fitInView."""
        rect = self._cena.sceneRect()
        if rect.isValid():
            self._view.reset_zoom(rect)

    def _atualizar_painel(self, medidas: dict):
        """
        Slot conectado ao sinal `medidas_atualizadas` da cena.
        Atualiza os labels com os novos comprimentos e recalcula o IPost.
        """
        for nome, lbl in self._labels_segmentos.items():
            valor = medidas.get(nome, 0.0)
            lbl.setText(f"  {nome}  = {valor:7.1f} px")

        dK = medidas.get("dK", 0.0)
        dS = medidas.get("dS", 0.0)
        dB = medidas.get("dB", 0.0)
        dL = medidas.get("dL", 0.0)

        denominador = dB + dL
        if denominador > 0:
            ipost = (dK + dS) / denominador
            self._ipost_valor = ipost
            self._label_ipost.setText(f"IPost = {ipost:.4f}")
        else:
            self._ipost_valor = None
            self._label_ipost.setText("IPost = —")

    def _resetar_painel(self):
        """Reseta os labels do painel lateral para zero."""
        for nome, lbl in self._labels_segmentos.items():
            lbl.setText(f"  {nome}  =   0.0 px")
        self._ipost_valor = None
        self._label_ipost.setText("IPost = —")

    def _exportar_imagem(self):
        """
        Renderiza o canvas em um QImage (resolução da cena), insere o valor do
        IPost no canto superior direito com fundo semitransparente e abre um
        diálogo de salvamento restrito ao formato PNG.
        """
        rect_cena = self._cena.sceneRect()
        if not rect_cena.isValid() or rect_cena.isEmpty():
            return

        # ── Escolhe o caminho de destino ───────────────────────────────
        caminho, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar Imagem",
            "ipost_resultado.png",
            "Imagem PNG (*.png)",
        )
        if not caminho:
            return
        if not caminho.lower().endswith(".png"):
            caminho += ".png"

        # ── Renderiza a cena inteira em um QImage ──────────────────────
        largura = int(rect_cena.width())
        altura = int(rect_cena.height())
        imagem = QImage(largura, altura, QImage.Format.Format_ARGB32)
        imagem.fill(QColor(0, 0, 0, 0))  # fundo transparente

        painter = QPainter(imagem)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        # Renderiza a cena completa (imagem de fundo + todos os itens gráficos)
        self._cena.render(painter, source=rect_cena)
        painter.end()

        # ── Insere o texto do IPost no canto superior direito ──────────
        if self._ipost_valor is not None:
            texto = f"IPost: {self._ipost_valor:.4f}"
        else:
            texto = "IPost: —"

        # Tamanho de fonte proporcional à resolução (≈ 2,5 % da altura, mín. 14 pt)
        tamanho_fonte = max(14, int(altura * 0.025))

        overlay_painter = QPainter(imagem)
        overlay_painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        fonte = QFont("Segoe UI", tamanho_fonte, QFont.Weight.Bold)
        overlay_painter.setFont(fonte)

        metricas = overlay_painter.fontMetrics()
        largura_texto = metricas.horizontalAdvance(texto)
        altura_texto = metricas.height()

        margem = int(tamanho_fonte * 0.6)
        padding_h = int(tamanho_fonte * 0.5)
        padding_v = int(tamanho_fonte * 0.3)

        # Retângulo do fundo semitransparente
        x_ret = largura - largura_texto - padding_h * 2 - margem
        y_ret = margem
        w_ret = largura_texto + padding_h * 2
        h_ret = altura_texto + padding_v * 2

        overlay_painter.setBrush(QColor(0, 0, 0, 160))   # preto 63% opaco
        overlay_painter.setPen(Qt.PenStyle.NoPen)
        overlay_painter.drawRoundedRect(x_ret, y_ret, w_ret, h_ret, 6, 6)

        # Contorno branco do texto (efeito de borda legível)
        overlay_painter.setPen(QColor(0, 0, 0, 200))
        for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            overlay_painter.drawText(
                x_ret + padding_h + dx,
                y_ret + padding_v + metricas.ascent() + dy,
                texto,
            )

        # Texto branco principal
        overlay_painter.setPen(QColor(255, 255, 255))
        overlay_painter.drawText(
            x_ret + padding_h,
            y_ret + padding_v + metricas.ascent(),
            texto,
        )

        overlay_painter.end()

        # ── Salva o arquivo PNG ────────────────────────────────────────
        imagem.save(caminho, "PNG")

    # ------------------------------------------------------------------
    # Redimensionamento
    # ------------------------------------------------------------------

    def resizeEvent(self, event):
        """
        Mantém a imagem ajustada ao redimensionar a janela,
        EXCETO quando o usuário já aplicou um zoom manual.
        Isso evita que o resize resete o nível de zoom do usuário.
        """
        super().resizeEvent(event)
        rect = self._cena.sceneRect()
        if rect.isValid() and not self._view.zoom_ativo:
            self._view.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
