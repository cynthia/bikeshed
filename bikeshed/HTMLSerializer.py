# -*- coding: utf-8 -*-

from __future__ import division, unicode_literals
try:
    from io import StringIO
except ImportError:
    import StringIO
from .htmlhelpers import childNodes, isElement, outerHTML, escapeHTML, escapeAttr, hasAttrs
from .messages import *


class HTMLSerializer(object):
    inlineEls = frozenset(["a", "em", "strong", "small", "s", "cite", "q", "dfn", "abbr", "data", "time", "code", "var", "samp", "kbd", "sub", "sup", "i", "b", "u", "mark", "ruby", "bdi", "bdo", "span", "br", "wbr", "img", "meter", "progress", "[]"])
    rawEls = frozenset(["xmp", "script", "style"])
    voidEls = frozenset(["area", "base", "br", "col", "command", "embed", "hr", "img", "input", "keygen", "link", "meta", "param", "source", "track", "wbr"])
    omitEndTagEls = frozenset(["td", "th", "tr", "thead", "tbody", "tfoot", "colgroup", "col", "li", "dt", "dd", "html", "head", "body"])

    def __init__(self, tree, opaqueElements, blockElements):
        self.tree = tree
        self.opaqueEls = frozenset(opaqueElements)
        self.blockEls = frozenset(blockElements)

    def serialize(self):
        output = StringIO.StringIO()
        writer = output.write
        writer("<!doctype html>")
        root = self.tree.getroot()
        self._serializeEl(root, writer)
        str = output.getvalue()
        output.close()
        return str

    def unfuckName(self, n):
        # LXML does namespaces stupidly
        if n.startswith("{"):
            return n.partition("}")[2]
        return n

    def groupIntoBlocks(self, nodes):
        collect = []
        for node in nodes:
            if self.isElement(node) and self.isBlockElement(node.tag):
                yield collect
                collect = []
                yield node
                continue
            else:
                collect.append(node)
        yield collect

    def fixWS(self, text):
        import string
        t1 = text.lstrip(string.whitespace)
        if text != t1:
            t1 = " " + t1
        t2 = t1.rstrip(string.whitespace)
        if t1 != t2:
            t2 = t2 + " "
        return t2

    def startTag(self, tag, el, write):
        if tag == "[]":
            return
        if not hasAttrs(el):
            write("<"+tag+">")
            return

        strs = []
        strs.append("<" + tag)
        for attrName, attrVal in sorted(el.items()):
            strs.append(" " + self.unfuckName(attrName) + '="' + escapeAttr(attrVal) + '"')
        strs.append(">")
        write("".join(strs))

    def endTag(self, tag, write):
        if tag != "[]":
            write("</" + tag + ">")

    def isElement(self, node):
        return isElement(node)

    def isAnonBlock(self, block):
        return not isElement(block)

    def isVoidElement(self, tag):
        return tag in self.voidEls

    def isRawElement(self, tag):
        return tag in self.rawEls

    def isOpaqueElement(self, tag):
        return tag in self.opaqueEls

    def isInlineElement(self, tag):
        return (tag in self.inlineEls) or ("-" in tag and tag not in self.blockEls)

    def isBlockElement(self, tag):
        return not self.isInlineElement(tag)

    def justWS(self, block):
        if self.isElement(block):
            return False
        return len(block) == 1 and not self.isElement(block[0]) and block[0].strip() == ""

    def _writeVoidElement(self, tag, el, write, indent):
        write(" " * indent)
        self.startTag(tag, el, write)

    def _writeRawElement(self, tag, el, write):
        self.startTag(tag, el, write)
        for node in childNodes(el):
            if self.isElement(node):
                die("Somehow a CDATA element got an element child:\n{0}", outerHTML(el))
                return
            else:
                write(node)
        self.endTag(tag, write)

    def _writeOpaqueElement(self, tag, el, write, indent):
        self.startTag(tag, el, write)
        for node in childNodes(el):
            if self.isElement(node):
                self._serializeEl(node, write, indent=indent, pre=True)
            else:
                write(escapeHTML(node))
        self.endTag(tag, write)

    def _writeInlineElement(self, tag, el, write, inline):
        self.startTag(tag, el, write)
        for node in childNodes(el):
            if self.isElement(node):
                self._serializeEl(node, write, inline=inline)
            else:
                write(escapeHTML(self.fixWS(node)))
        self.endTag(tag, write)

    def _blocksFromChildren(self, children):
        return [block for block in self.groupIntoBlocks(children) if not self.justWS(block)]

    def _categorizeBlockChildren(self, el):
        '''
        Figure out what sort of contents the block has,
        so we know what serialization strategy to use.
        '''
        if len(el) == 0 and (el.text is None or el.text.strip() == ""):
            return "empty", None
        children = childNodes(el)
        for child in children:
            if self.isElement(child) and self.isBlockElement(child.tag):
                return "blocks", self._blocksFromChildren(children)
        return "inlines", children

    def _writeBlockElement(self, tag, el, write, indent):
        # Dropping pure-WS anonymous blocks.
        # This maintains whitespace between *inline* elements, which is required.
        # It just avoids serializing a line of "inline content" that's just WS.
        contentsType, contents = self._categorizeBlockChildren(el)

        if contentsType == "empty":
            # Empty of text and children
            write(" " * indent)
            self.startTag(tag, el, write)
            if el.tag not in self.omitEndTagEls:
                self.endTag(tag, write)
        elif contentsType == "inlines":
            # Contains only inlines, print accordingly
            write(" " * indent)
            self.startTag(tag, el, write)
            self._serializeEl(contents, write, inline=True)
            if el.tag not in self.omitEndTagEls:
                self.endTag(tag, write)
            return
        else:
            # Otherwise I'm a block that contains at least one block
            write(" " * indent)
            self.startTag(tag, el, write)
            for block in contents:
                if isinstance(block, list):
                    # is an array of inlines
                    if len(block) > 0:
                        write("\n" + (" " * (indent + 1)))
                        self._serializeEl(block, write, inline=True)
                else:
                    write("\n")
                    self._serializeEl(block, write, indent=indent + 1)
            if tag not in self.omitEndTagEls:
                write("\n" + (" " * indent))
                self.endTag(tag, write)

    def _serializeEl(self, el, write, indent=0, pre=False, inline=False):
        if isinstance(el, list):
            tag = "[]"
        else:
            tag = self.unfuckName(el.tag)

        if self.isVoidElement(tag):
            self._writeVoidElement(tag, el, write, indent)
        elif self.isRawElement(tag):
            self._writeRawElement(tag, el, write)
        elif pre or self.isOpaqueElement(tag):
            self._writeOpaqueElement(tag, el, write, indent)
        elif inline or self.isInlineElement(el):
            self._writeInlineElement(tag, el, write, inline)
        else:
            self._writeBlockElement(tag, el, write, indent)
