# Got It! para Windows

App de notas da Color Software para Windows 10 e 11, irmão do Got It! para iPhone e iPad: texto como no Word, objetos soltos na página, tinta com a pressão da caneta, todas as mídias, Teias e inteligência que roda no próprio computador. Nada das notas sai do computador.

## Instalar

1. Na página **Releases** deste repositório, baixe o **GotIt_Setup_x.y.z.exe** (“Got It! para Windows (última versão)”).
2. Dê dois cliques. Como o instalador não tem assinatura digital de empresa, o Windows pode mostrar “O Windows protegeu o computador”: clique em **Mais informações** e depois em **Executar assim mesmo**.
3. O instalador não pede senha de administrador (instala para a sua conta). Para atualizar, rode a versão nova por cima: as notas continuam.

O instalador é gerado no GitHub a cada mudança, num Windows de verdade, com os testes rodando antes. Para gerar no próprio computador, dê dois cliques em **GERAR_INSTALADOR.bat**.

## O que tem

**Menu (à esquerda, como no iPad)**
- Nova nota, nova nota simples, nova Teia e nova pasta; as 9 notas e as 9 Teias mais recentes da pasta mostrada, com a prévia da primeira página, e “Todas as Notas” / “Todas as Teias”.
- **Pastas por arrastar:** solte uma nota sobre outra e nasce uma pasta com as duas (“Pasta N”, dá para dar nome na hora). Solte sobre uma pasta para mover; sobre “Voltar para…” para subir; sobre a Lixeira para apagar.
- **Busca** em todas as notas: acentos e maiúsculas não contam e o começo da palavra basta (“indeniz” acha “Indenização”). Entram texto, caixas, post-its, formas, tabelas, transcrições e legendas. Com a busca por significado ligada, aparece também “Por significado”.
- **Lixeira**: nada é apagado sozinho; restaurar, apagar para sempre ou esvaziar.
- Marca da Color Software no rodapé.

**A nota**
- Página A4 (ou outro tamanho, em cm), uma embaixo da outra, com as margens “Normal” do Word (2,5 cm em cima e embaixo, 3 cm nos lados). O texto passa sozinho para a página seguinte.
- Formatação como no Word: estilos (Título, Subtítulo, Título 1 e 2, Corpo, Citação), fonte, tamanho, negrito, itálico, sublinhado, tachado, cor, marca-texto em 5 cores, alinhamento, listas, recuos, espaço entre linhas, links (web, e-mail e **links entre notas**), localizar e substituir. A barra mostra o que está ligado onde está o cursor.
- **Tabelas** no texto ou soltas na página: linhas, colunas, linha de cabeçalho, cor da célula, borda; Tab passa de célula.
- **Objetos** que se arrastam, redimensionam e giram, com guias de alinhamento (estilo Canva): caixa de texto, formas (retângulo, elipse, losango, triângulo, linha, seta) com texto dentro e cores de contorno e preenchimento, **conexões** entre objetos que acompanham quando eles se mexem, **post-it** em 5 cores, **calendário** com o dia (dois cliques mudam a data), **stickers** (emoji ou imagem), imagens (recortar, formato em elipse/losango/triângulo, remover o fundo de papel), **PDF** (abre num leitor) e **PDF para anotar** (cada página do PDF vira uma página da nota, para escrever por cima), **áudio** (gravar pelo microfone ou importar; toca no próprio bloco) e **vídeo**. Objetos novos entram no primeiro espaço livre; objeto arrastado fica por cima.
- **Tinta**: caneta com pressão (Windows Ink), marcador, lápis, borracha (o traço inteiro ou só a parte tocada) e laço para selecionar e mover. O mouse também desenha.
- **Formas perfeitas**: retângulo, elipse, losango, triângulo, linha e seta desenhados à mão viram formas editáveis; uma linha ligando duas formas vira conexão.
- **Página**: cabeçalho e rodapé (texto, imagem ou a primeira página de um PDF; o texto da nota fica entre eles; aviso quando um objeto invade), números de página (posição, formato, número inicial, tamanho), **papel** liso, caderno (o texto cai nas pautas), quadriculado ou xadrez, na nota toda, numa página ou em meia página.
- **Nota simples**: meia folha A4 amarela pautada, com margem vermelha, só para escrever.
- Painel de páginas com miniaturas, zoom (Ctrl + roda), desfazer e refazer de tudo (Ctrl+Z / Ctrl+Y), gravação automática.
- **Exportar como PDF** (texto continua texto) e **imprimir**. Duplicar a nota, mover para pasta, “Citada em…”.

**Teias**
- Página em paisagem com cartões das notas escolhidas (nome, data de criação e prévia). A nota não é copiada: dois cliques abrem a nota. Setas discretas mostram a ordem de criação; ligações próprias, post-its, formas e tinta como numa nota.

**Inteligência no computador** (cada modelo é baixado uma vez, só quando você pede, e conferido pelo SHA-256)
- **Assistente** (Gemma 4 E2B, 2,6 GB — o mesmo modelo e o mesmo motor, LiteRT-LM, do Got It! para iPhone): resumir a nota (cerca de 1/5 dela, com as pendências no fim), perguntas para revisar, organizar a nota (título, pasta e pendências propostos para você aceitar) e perguntar às notas, com as fontes citadas. A resposta pode ser copiada ou inserida na nota.
- **Busca por significado** (EmbeddingGemma, 165 MB).
- **Transcrição de áudio** (Whisper small, 484 MB): num bloco próprio ao lado do áudio ou no texto da nota.
- **Escrita vira texto** e **equações escritas à mão resolvidas** (até o 2º grau), pelo reconhecimento de escrita do próprio Windows. Para português, instale o manuscrito em Configurações › Hora e idioma › Idioma e região › Português (Brasil) › Opções de idioma.

## Onde ficam as notas

Em `%LOCALAPPDATA%\Color Software\Got It` (banco SQLite + mídias por SHA-256). Em **Ajustes** dá para abrir a pasta, fazer uma **cópia de segurança** completa numa pasta comum (pendrive, HD externo, OneDrive) e restaurar sem duplicar notas.

## Diferenças em relação ao iPhone (adaptações do Windows)

- **Remover o fundo**: no iPhone, fotos usam o recorte de objeto da Apple (Vision). No Windows não há equivalente pronto; aqui o recurso funciona para desenhos e textos em papel ou quadro branco (o papel fica transparente), com prévia e sensibilidade.
- **Transcrição**: no iPhone é o SpeechAnalyzer da Apple; aqui é o Whisper, também no computador.
- **Escrita vira texto**: no iPhone é o Vision; aqui é o reconhecedor de escrita do Windows.
- **Texto em volta dos objetos**: os objetos ficam por cima do texto (no iPhone o texto contorna). O espaço livre para objetos novos considera o texto já escrito.
- **Apagar deslizando** vira: tecla Delete, botão direito › Apagar, ou arrastar a nota até a Lixeira.

## Para quem for mexer no código

```
app/                Python + Qt (PySide6)
  main.py           entrada (--demo, --screen, --shot, --self-test)
  window.py         janela principal; sidebar.py: menu, pastas, busca
  editor.py         editor da nota; editor_ui.py: barra, ferramentas, páginas
  canvas.py         páginas, texto paginado, papel, cabeçalho e rodapé; canvas_view.py: zoom, caneta
  items.py          objetos; ink.py: tinta e borracha; shapes.py: formas perfeitas
  textfmt.py        formatação; undo.py: desfazer único; store.py: SQLite, FTS5, pastas, Lixeira
  assistant.py      Gemma 4 E2B; semantic.py: EmbeddingGemma; speech.py: Whisper; models.py: downloads
  handwriting.py    Windows Ink; mathsolve.py: equações; cutout.py: remover o fundo
build/              PyInstaller, Inno Setup e build.ps1
tests/              pytest (rodam no Linux sem tela e no Windows do CI)
```

Formato das notas: JSON com os mesmos nomes de campos do Got It! para iPhone (`CanvasDocument`), com o texto principal em HTML do Qt.

Licença: AGPL-3.0 (arquivo LICENSE). Fontes Caveat, Patrick Hand, Kalam e Indie Flower: SIL Open Font License (assets/fonts).
