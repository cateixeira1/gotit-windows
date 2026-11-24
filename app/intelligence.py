"""Inteligência local do Got It! no Windows (tudo no computador, sem enviar notas):

- escrita à mão vira texto: reconhecimento de escrita do próprio Windows (Windows Ink);
- equações escritas à mão: lidas pelo mesmo reconhecimento e resolvidas sem IA (até 2º grau);
- transcrição de áudio: Whisper (faster-whisper), com o modelo baixado só quando pedido;
- assistente e busca por significado: LiteRT-LM com Gemma 4 E2B e EmbeddingGemma, os mesmos
  modelos e o mesmo motor do Got It! para iPhone;
- remover fundo de imagens: papel/quadro (limiar adaptativo) no computador.

Cada parte é opcional: sem o componente, o app explica o que falta em vez de falhar."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox


class Intelligence:
    def __init__(self, window):
        self.window = window
        self._handwriting = None
        self._assistant = None
        self._semantic = None
        self._speech = None

    # ------------------------------------------------------------------ escrita à mão
    def handwriting_available(self) -> bool:
        import handwriting
        return handwriting.available()

    def explain_handwriting(self) -> None:
        import handwriting
        QMessageBox.information(self.window, "Escrita vira texto", handwriting.explanation())

    def recognize_handwriting(self, editor, stroke_ids, new_ids=None) -> None:
        import handwriting
        handwriting.recognize_into(editor, stroke_ids, new_ids)

    # ------------------------------------------------------------------ áudio
    def transcribe(self, editor, item) -> None:
        import speech
        speech.transcribe(self.window, editor, item)

    # ------------------------------------------------------------------ imagens
    def remove_background(self, editor, item) -> None:
        import cutout
        cutout.remove_background(self.window, editor, item)

    # ------------------------------------------------------------------ assistente
    def assistant_visible(self) -> bool:
        return True

    def open_assistant(self, prefill: str = "") -> None:
        import assistant
        assistant.open_panel(self.window, prefill)

    def search_by_meaning(self, query: str, exclude: set) -> list:
        try:
            import semantic
        except Exception:
            return []
        return semantic.search(self.window, query, exclude)

    def note_saved(self, doc_id: str) -> None:
        import sys
        if "semantic" in sys.modules or self.window.settings.value("semanticSearch", "false") == "true":
            try:
                import semantic
                semantic.note_changed(self.window, doc_id)
            except Exception:
                pass

    def semantic_ready(self) -> None:
        try:
            import semantic
            idx = semantic.index(self.window)
            if idx is not None:
                idx.schedule_all()
        except Exception:
            pass

    def release(self, key: str) -> None:
        import sys
        mod = sys.modules.get({"assistant": "assistant", "semantic": "semantic", "speech": "speech"}[key])
        if mod is not None and hasattr(mod, "shutdown"):
            mod.shutdown()
        if key == "semantic":
            self.window.settings.setValue("semanticSearch", "false")

    def shutdown(self) -> None:
        for name in ("assistant", "semantic", "speech"):
            mod = __import__("sys").modules.get(name)
            if mod is not None and hasattr(mod, "shutdown"):
                try:
                    mod.shutdown()
                except Exception:
                    pass
