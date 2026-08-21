# SEND — Makefile de instalação (Linux / macOS)
#
# Depois de clonar o repositório:
#   make install     # instala o SEND em ~/.local/bin/send (Linux/macOS)
#   make install-system  # instala em /usr/local/bin/send (precisa de sudo)
#   make uninstall   # remove a instalação
#   make test        # roda a suíte de testes
#   make update      # atualiza o SEND pelo próprio comando (send --update)

PREFIX ?= $(HOME)/.local/bin
SYSTEM_PREFIX ?= /usr/local/bin
PY ?= python3

install:
	@mkdir -p $(PREFIX)
	@cp send.py $(PREFIX)/send
	@chmod +x $(PREFIX)/send
	@echo "✅ SEND instalado em $(PREFIX)/send"
	@if echo "$$PATH" | grep -q "$(PREFIX)"; then \
		echo "   Já está no PATH — rode: send"; \
	else \
		echo "⚠ Adicione $(PREFIX) ao seu PATH:"; \
		echo '    echo '"'"'export PATH="$(PREFIX):$$PATH"'"'"' >> ~/.bashrc && source ~/.bashrc'; \
	fi
	@echo "   Depois: send --doctor  (testa a conexão com o LM Studio)"

install-system:
	@sudo mkdir -p $(SYSTEM_PREFIX)
	@sudo cp send.py $(SYSTEM_PREFIX)/send
	@sudo chmod +x $(SYSTEM_PREFIX)/send
	@echo "✅ SEND instalado em $(SYSTEM_PREFIX)/send — rode: send"

uninstall:
	@rm -f $(PREFIX)/send
	@echo "🗑  SEND removido de $(PREFIX)/send"
	@echo "   (opcional) remova também a pasta de dados: rm -rf ~/.send"

test:
	@bash tests/run_tests.sh

update:
	@python3 send.py --update

.PHONY: install install-system uninstall test update
