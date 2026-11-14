CXX = g++
CPPFLAGS += $(shell pkg-config --cflags hyprland)
CXXFLAGS ?= -O2 -g
CXXFLAGS += -std=c++23 -fPIC -Wall -Wextra -Wno-unused-parameter

PREFIX ?= $(HOME)/.local
COMPANION_DIR = $(DESTDIR)$(PREFIX)/share/hypr-underlay/omarchy-plugin

.PHONY: all check install install-companion uninstall validate
all: build/hypr-underlay.so

build/hypr-underlay.so: src/main.cpp
	mkdir -p build
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(LDFLAGS) -shared -o $@.new $<
	mv $@.new $@

check:
	python3 -m unittest discover -s tests -v
	lua tests/shortcut.lua

install: all install-companion
	install -d "$(DESTDIR)$(PREFIX)/lib/hypr-underlay" "$(DESTDIR)$(PREFIX)/bin"
	install -m 755 build/hypr-underlay.so "$(DESTDIR)$(PREFIX)/lib/hypr-underlay/hypr-underlay.so.new"
	mv "$(DESTDIR)$(PREFIX)/lib/hypr-underlay/hypr-underlay.so.new" "$(DESTDIR)$(PREFIX)/lib/hypr-underlay/hypr-underlay.so"
	install -m 755 tools/hypr_underlay.py "$(DESTDIR)$(PREFIX)/bin/hypr-underlay.new"
	mv "$(DESTDIR)$(PREFIX)/bin/hypr-underlay.new" "$(DESTDIR)$(PREFIX)/bin/hypr-underlay"

install-companion:
	install -d "$(COMPANION_DIR)/omarchy" "$(COMPANION_DIR)/hypr" "$(COMPANION_DIR)/tools"
	install -m 644 manifest.json "$(COMPANION_DIR)/manifest.json"
	install -m 644 omarchy/Underlay.qml "$(COMPANION_DIR)/omarchy/Underlay.qml"
	install -m 644 hypr/shortcut.lua "$(COMPANION_DIR)/hypr/shortcut.lua"
	install -m 644 tools/hypr_underlay.py "$(COMPANION_DIR)/tools/hypr_underlay.py"

uninstall:
	@if [ -z "$(DESTDIR)" ]; then python3 tools/hypr_underlay.py off --if-active; fi
	rm -f "$(DESTDIR)$(PREFIX)/bin/hypr-underlay" "$(DESTDIR)$(PREFIX)/lib/hypr-underlay/hypr-underlay.so"
	rm -f "$(COMPANION_DIR)/manifest.json" "$(COMPANION_DIR)/omarchy/Underlay.qml" "$(COMPANION_DIR)/hypr/shortcut.lua" "$(COMPANION_DIR)/tools/hypr_underlay.py"
	-rmdir "$(COMPANION_DIR)/omarchy" "$(COMPANION_DIR)/hypr" "$(COMPANION_DIR)/tools" "$(COMPANION_DIR)"
	-rmdir "$(DESTDIR)$(PREFIX)/lib/hypr-underlay"

validate:
	luac -p hypr/shortcut.lua
	omarchy plugin validate "$(CURDIR)"
