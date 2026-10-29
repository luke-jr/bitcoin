#!/usr/bin/env python3
# Copyright (c) 2026 The Bitcoin Knots developers
# Distributed under the MIT software license, see the accompanying file COPYING.

"""Compile Android signature-format 2.0 source into a deterministic JVM API jar tree.

These are compile-time stubs, never device classes. Direct class-file emission
preserves the specified public ABI without inventing visible constructors or
abstract-method implementations to satisfy javac. Concrete methods contain only
aconst_null/athrow; native and abstract methods have no Code attribute.

Descriptors, generic signatures and bounds, constants, exceptions, nested-class
metadata, annotation defaults, and public runtime annotations come from the API
source. Annotations absent from the public API are omitted.
The output targets class-file version 52, matching Java 8 application builds.
"""
import argparse
import ast
import base64
import dataclasses
import math
import re
import struct
from pathlib import Path
U1 = lambda x: struct.pack('>B', x)
U2 = lambda x: struct.pack('>H', x)
U4 = lambda x: struct.pack('>I', x)
MODS = {'public': 1, 'private': 2, 'protected': 4, 'static': 8, 'final': 16, 'synchronized': 32, 'volatile': 64, 'transient': 128, 'native': 256, 'abstract': 1024, 'strictfp': 2048, 'default': 0, 'deprecated': 0}
PRIMITIVES = dict(zip(('byte', 'char', 'double', 'float', 'int', 'long', 'short', 'boolean', 'void'), 'BCDFIJSZV'))

def annotation_spans(text):
    """Find annotations outside literals, retaining their original positions."""
    i = 0
    while i < len(text):
        if text[i] in '\"\'':
            quote = text[i]
            i += 1
            while i < len(text) and text[i] != quote:
                i += 2 if text[i] == '\\' else 1
            if i >= len(text):
                raise ValueError('Unterminated quoted literal')
            i += 1
            continue
        if text[i] != '@' or text.startswith('@interface', i):
            i += 1
            continue
        start = i
        i += 1
        name_start = i
        while i < len(text) and (text[i].isalnum() or text[i] in '._$'):
            i += 1
        name = text[name_start:i]
        if not name:
            raise ValueError('Missing annotation name')
        value = None
        if i < len(text) and text[i] == '(':
            i += 1
            value_start = i
            depth = 1
            quote = None
            while depth:
                if i >= len(text):
                    raise ValueError('Unterminated annotation')
                char = text[i]
                i += 1
                if quote:
                    if char == '\\':
                        i += 1
                    elif char == quote:
                        quote = None
                elif char in '\"\'':
                    quote = char
                elif char == '(':
                    depth += 1
                elif char == ')':
                    depth -= 1
            value = text[value_start:i - 1]
        yield start, i, name, value


def strip_annotations(text):
    out = []
    previous = 0
    for start, end, _, _ in annotation_spans(text):
        out.extend((text[previous:start], ' '))
        previous = end
    return ''.join(out) + text[previous:]

def split_values(text):
    values = []
    start = 0
    depth = 0
    quote = None
    i = 0
    while i < len(text):
        c = text[i]
        if quote:
            if c == '\\':
                i += 1
            elif c == quote:
                quote = None
        elif c in '"\'':
            quote = c
        elif c in '({[':
            depth += 1
        elif c in ')}]':
            depth -= 1
        elif c == ',' and depth == 0:
            values.append(text[start:i].strip())
            start = i + 1
        i += 1
    if text[start:].strip():
        values.append(text[start:].strip())
    return values

def annotations(text):
    return [(name, value) for _, _, name, value in annotation_spans(text)]


def strip_line_comment(text):
    quote = None
    i = 0
    while i < len(text):
        char = text[i]
        if quote:
            if char == '\\':
                i += 1
            elif char == quote:
                quote = None
        elif char in '\"\'':
            quote = char
        elif text.startswith('//', i):
            return text[:i].rstrip()
        i += 1
    return text

@dataclasses.dataclass
class Type:
    name: str
    arguments: list = dataclasses.field(default_factory=list)
    arrays: int = 0

class Parser:

    def __init__(self, s):
        self.tokens = re.findall('@interface|\\.\\.\\.|[\\w$]+(?:\\.[\\w$]+)*|[^\\s]', s)
        self.i = 0

    def peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def pop(self, expected=None):
        t = self.peek()
        if t is None:
            raise ValueError('Unexpected end of API declaration')
        self.i += 1
        if expected is not None and t != expected:
            raise ValueError((expected, t, self.tokens))
        return t

    def modifiers(self):
        out = 0
        while self.peek() in MODS:
            out |= MODS[self.pop()]
        return out

    def type(self):
        name = self.pop()
        arguments = []
        if name == '?':
            if self.peek() in ('extends', 'super'):
                return Type(self.pop(), [self.type()])
            return Type('?')
        if self.peek() == '<':
            self.pop()
            while True:
                arguments.append(self.type())
                delimiter = self.pop()
                if delimiter == '>':
                    break
                if delimiter != ',':
                    raise ValueError('Expected comma between type arguments')
        arrays = 0
        while self.peek() in ('[', '...'):
            token = self.pop()
            if token == '[':
                self.pop(']')
            arrays += 1
        return Type(name, arguments, arrays)

    def formals(self):
        formals = {}
        if self.peek() != '<':
            return formals
        self.pop()
        while True:
            name = self.pop()
            bounds = []
            if self.peek() == 'extends':
                self.pop()
                bounds.append(self.type())
                while self.peek() == '&':
                    self.pop()
                    bounds.append(self.type())
            if name in formals:
                raise ValueError('Duplicate type parameter ' + name)
            formals[name] = bounds or [Type('java.lang.Object')]
            delimiter = self.pop()
            if delimiter == '>':
                break
            if delimiter != ',':
                raise ValueError('Expected comma between type parameters')
        return formals

@dataclasses.dataclass
class Class:
    package: str
    name: str
    flags: int
    kind: str
    formals: dict
    superclass: Type
    interfaces: list
    members: list = dataclasses.field(default_factory=list)
    annotations: list = dataclasses.field(default_factory=list)

    def full(self):
        return self.package + '.' + self.name

    def binary(self):
        return self.package.replace('.', '/') + '/' + self.name.replace('.', '$')

def load(path, base64_encoded=False):
    data = path.read_bytes()
    text = (base64.b64decode(data, validate=True) if base64_encoded else data).decode("utf-8")
    classes = {}
    current = None
    package = None
    if not text.startswith('// Signature format: 2.0\n'):
        raise ValueError('Only Android signature format 2.0 is supported')
    for number, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith('//'):
            continue
        try:
            if s.startswith('package '):
                match = re.fullmatch(r'package ([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*) \{', s)
                if not match or package is not None:
                    raise ValueError('Invalid or nested package declaration')
                package = match[1]
                continue
            if s == '}':
                if current is not None:
                    current = None
                elif package is not None:
                    package = None
                else:
                    raise ValueError('Unmatched closing brace')
                continue
            if line.startswith('  ') and (not line.startswith('    ')):
                if package is None or current is not None or not s.endswith(' {'):
                    raise ValueError('Class outside package, nested class body, or missing brace')
                p = Parser(strip_annotations(s[:-1]))
                flags = p.modifiers()
                kind = p.pop()
                name = p.pop()
                if kind not in ('class', 'interface', '@interface', 'enum'):
                    raise ValueError('Unknown class kind ' + kind)
                if not re.fullmatch(r'[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*', name):
                    raise ValueError('Invalid class name ' + name)
                formals = p.formals()
                superclass = Type('java.lang.Object')
                interfaces = []
                if kind == 'enum':
                    superclass = Type('java.lang.Enum', [Type(package + '.' + name)])
                if kind == '@interface':
                    interfaces = [Type('java.lang.annotation.Annotation')]
                while p.peek():
                    key = p.pop()
                    if key == 'extends' and kind not in ('interface', '@interface'):
                        superclass = p.type()
                    elif key in ('extends', 'implements'):
                        while p.peek():
                            interfaces.append(p.type())
                            if p.peek() == ',':
                                p.pop()
                    else:
                        raise ValueError(key)
                current = Class(package, name, flags, kind, formals, superclass, interfaces, annotations=annotations(s))
                if current.full() in classes:
                    raise ValueError('Duplicate class ' + current.full())
                classes[current.full()] = current
            else:
                if current is None or not line.startswith('    '):
                    raise ValueError('Member outside class')
                current.members.append((number, s))
        except Exception as e:
            raise ValueError(f'line {number}: {s}') from e
    if package is not None or current is not None:
        raise ValueError('Unclosed package or class at end of API source')
    return classes

class Pool:

    def __init__(self):
        self.items = [None]
        self.lookup = {}

    def add(self, tag, payload):
        key = (tag, payload)
        if key not in self.lookup:
            self.lookup[key] = len(self.items)
            self.items.append(U1(tag) + payload)
            if tag in (5, 6):
                self.items.append(b'')
        return self.lookup[key]

    def utf(self, text):
        units = struct.unpack('>' + 'H' * (len(text.encode('utf-16-be', errors='surrogatepass')) // 2), text.encode('utf-16-be', errors='surrogatepass'))
        out = b''
        for v in units:
            out += U1(v) if 0 < v < 128 else bytes((192 | v >> 6, 128 | v & 63)) if v < 2048 else bytes((224 | v >> 12, 128 | v >> 6 & 63, 128 | v & 63))
        return self.add(1, U2(len(out)) + out)

    def cls(self, name):
        return self.add(7, U2(self.utf(name)))

    def serialize(self):
        return U2(len(self.items)) + b''.join((x for x in self.items[1:]))

class Compiler:

    def __init__(self, classes):
        self.classes = classes

    def binary(self, name):
        if name in self.classes:
            return self.classes[name].binary()
        if '.' not in name:
            name = 'java.lang.' + name
        if name in self.classes:
            return self.classes[name].binary()
        raise ValueError('unknown class ' + name)

    def signature(self, t, env, erase=False):
        if t.name == 'void' and t.arrays:
            raise ValueError('void cannot be an array element')
        if t.name == '?':
            s = '*'
        elif t.name in ('extends', 'super'):
            s = ('+' if t.name == 'extends' else '-') + self.signature(t.arguments[0], env, erase)
        elif t.name in PRIMITIVES:
            s = PRIMITIVES[t.name]
        elif t.name in env:
            s = self.signature(env[t.name][0], {k: v for k, v in env.items() if k != t.name}, True) if erase else 'T' + t.name + ';'
        else:
            s = 'L' + self.binary(t.name) + ('' if erase or not t.arguments else '<' + ''.join((self.signature(a, env) for a in t.arguments)) + '>') + ';'
        return '[' * t.arrays + s

    def formals(self, formals, env):
        if not formals:
            return ''
        result = '<'
        for name, bounds in formals.items():
            first = self.classes.get(bounds[0].name) or self.classes.get('java.lang.' + bounds[0].name)
            interface = first and first.kind in ('interface', '@interface')
            result += name + (':' if interface else '') + ''.join((':' + self.signature(t, env) for t in bounds))
        return result + '>'

    def emit(self, c):
        pool = Pool()
        attributes = []
        fields = []
        methods = []
        seen_members = set()
        env = {}
        for i in range(1, len(c.name.split('.')) + 1):
            owner = self.classes[c.package + '.' + '.'.join(c.name.split('.')[:i])]
            if owner.flags & 8 or owner.kind in ('interface', '@interface', 'enum'):
                env.clear()
            env.update(owner.formals)

        def attr(name, data):
            return U2(pool.utf(name)) + U4(len(data)) + data

        def member(flags, name, descriptor, attrs):
            key = (name, descriptor)
            if key in seen_members:
                raise ValueError('Duplicate member ' + name + descriptor)
            seen_members.add(key)
            return U2(flags) + U2(pool.utf(name)) + U2(pool.utf(descriptor)) + U2(len(attrs)) + b''.join(attrs)

        def number_constant(descriptor, value):
            if descriptor in ('J', 'I', 'S', 'B', 'C', 'Z'):
                if value in ('true', 'false'):
                    n = int(value == 'true')
                elif value.startswith("'"):
                    n = ord(ast.literal_eval(value))
                else:
                    n = int(value.rstrip('lL'), 0)
                width = 64 if descriptor == 'J' else 32
                return pool.add(5 if width == 64 else 3, (n % 2 ** width).to_bytes(width // 8, 'big'))
            if descriptor in ('F', 'D'):
                value = value.replace('f', '').replace('F', '').replace('d', '').replace('D', '')
                if '/0.0' in value:
                    n = math.nan if value.startswith('(0.0') else -math.inf if value.startswith('(-') else math.inf
                else:
                    n = float(value)
                return pool.add(4 if descriptor == 'F' else 6, struct.pack('>f' if descriptor == 'F' else '>d', n))
            raise ValueError('numeric annotation ' + descriptor)

        def annotation_type(name):
            if name in self.classes:
                return self.classes[name]
            return self.classes.get('java.lang.' + name)

        def annotation_value(t, value):
            if t.arrays:
                element = dataclasses.replace(t, arrays=t.arrays - 1)
                values = split_values(value[1:-1]) if value.startswith('{') else [value]
                return b'[' + U2(len(values)) + b''.join((annotation_value(element, v) for v in values))
            descriptor = self.signature(t, env, True)
            if descriptor in ('B', 'C', 'D', 'F', 'I', 'J', 'S', 'Z'):
                return descriptor.encode() + U2(number_constant(descriptor, value))
            if descriptor == 'Ljava/lang/String;':
                return b's' + U2(pool.utf(ast.literal_eval(value)))
            if descriptor == 'Ljava/lang/Class;':
                if not value.endswith('.class'):
                    raise ValueError(value)
                return b'c' + U2(pool.utf(self.signature(Parser(value[:-6]).type(), env, True)))
            if value.startswith('@'):
                return b'@' + annotation(*annotations(value)[0])
            return b'e' + U2(pool.utf(descriptor)) + U2(pool.utf(value.rsplit('.', 1)[-1]))

        def annotation(name, value):
            schema = annotation_type(name)
            if schema is None:
                raise ValueError('annotation ' + name)
            elements = {}
            for _, line in schema.members:
                if line.startswith('method '):
                    p = Parser(strip_annotations(line[7:]))
                    p.modifiers()
                    t = p.type()
                    elements[p.pop()] = t
            values = []
            seen_elements = set()
            for entry in split_values(value or ''):
                assignment = re.fullmatch('\\s*(\\w+)\\s*=(.*)', entry, re.S)
                if assignment:
                    key, raw = assignment.groups()
                else:
                    key, raw = ('value', entry)
                key = key.strip()
                if key in seen_elements:
                    raise ValueError('Duplicate annotation element ' + key)
                seen_elements.add(key)
                values.append(U2(pool.utf(key)) + annotation_value(elements[key], raw.strip()))
            return U2(pool.utf('L' + schema.binary() + ';')) + U2(len(values)) + b''.join(values)

        def annotation_attribute(items):
            groups = {"RuntimeVisibleAnnotations": [], "RuntimeInvisibleAnnotations": []}
            for name, value in items:
                schema = annotation_type(name)
                if schema is None:
                    continue
                retention = next((v for n, v in schema.annotations
                                  if n == "java.lang.annotation.Retention"), "CLASS")
                if retention.endswith("SOURCE"):
                    continue
                attribute = ("RuntimeVisibleAnnotations" if retention.endswith("RUNTIME")
                             else "RuntimeInvisibleAnnotations")
                groups[attribute].append(annotation(name, value))
            return [attr(name, U2(len(values)) + b"".join(values))
                    for name, values in groups.items() if values]
        attributes.extend(annotation_attribute(c.annotations))
        for line_number, line in c.members:
            try:
                category, text = line.split(' ', 1)
                text = strip_line_comment(text)
                if not text.endswith(';'):
                    raise ValueError('Missing member terminator')
                raw_text = text[:-1].rstrip()
                # An annotation in a parameter or annotation default is not a
                # declaration annotation on the containing method. Preserve
                # positions while locating the declaration's parameter list.
                masked = list(text)
                spans = list(annotation_spans(text))
                for start, end, _, _ in spans:
                    masked[start:end] = ' ' * (end - start)
                boundary = ''.join(masked).find('(' if category in ('method', 'ctor') else '=')
                declaration_annotations = [(name, value) for start, _, name, value in spans
                                           if boundary < 0 or start < boundary]
                if category in ('method', 'ctor') and boundary >= 0:
                    parameter_end = ''.join(masked).find(')', boundary)
                    if any(boundary < start < parameter_end and annotation_type(name) is not None
                           for start, _, name, _ in spans):
                        # The pinned public API has no such annotations. Do
                        # not silently attach them to the method if that changes.
                        raise ValueError('Public parameter annotations are not supported')
                text = strip_annotations(raw_text)
                p = Parser(text)
                flags = p.modifiers()
                attrs = annotation_attribute(declaration_annotations)
                if category in ('field', 'enum_constant'):
                    t = p.type()
                    name = p.pop()
                    if p.peek() not in (None, '='):
                        raise ValueError('Unexpected tokens after field name')
                    descriptor = self.signature(t, env, True)
                    if descriptor == 'V':
                        raise ValueError('Field cannot have void type')
                    signature = self.signature(t, env)
                    if descriptor != signature:
                        attrs.append(attr('Signature', U2(pool.utf(signature))))
                    if category == 'enum_constant':
                        flags |= 16384
                    if p.peek() == '=':
                        value = text.split(' = ', 1)[1]
                        if descriptor == 'Ljava/lang/String;':
                            index = pool.add(8, U2(pool.utf(ast.literal_eval(value))))
                        elif descriptor in ('J', 'I', 'S', 'B', 'C', 'Z'):
                            if value in ('true', 'false'):
                                n = int(value == 'true')
                            elif value.startswith("'"):
                                n = ord(ast.literal_eval(value))
                            else:
                                n = int(value.rstrip('lL'), 0)
                            width = 64 if descriptor == 'J' else 32
                            index = pool.add(5 if width == 64 else 3, (n % 2 ** width).to_bytes(width // 8, 'big'))
                        elif descriptor in ('F', 'D'):
                            value = value.replace('f', '').replace('F', '').replace('d', '').replace('D', '')
                            if '/0.0' in value:
                                n = math.nan if value.startswith('(0.0') else -math.inf if value.startswith('(-') else math.inf
                            else:
                                n = float(value)
                            index = pool.add(4 if descriptor == 'F' else 6, struct.pack('>f' if descriptor == 'F' else '>d', n))
                        else:
                            raise ValueError('constant ' + descriptor)
                        attrs.append(attr('ConstantValue', U2(index)))
                    fields.append(member(flags, name, descriptor, attrs))
                    continue
                if category not in ('method', 'ctor'):
                    raise ValueError(category)
                if c.kind in ('interface', '@interface') and (not flags & (8 | 2)) and ('default ' not in text):
                    flags |= 1024
                formals = p.formals()
                menv = env | formals
                if category == 'ctor':
                    if p.pop() != c.name:
                        raise ValueError('Constructor name does not match class')
                    name = '<init>'
                    returns = Type('void')
                else:
                    returns = p.type()
                    name = p.pop()
                p.pop('(')
                parameters = []
                varargs = False
                while p.peek() != ')':
                    parameter_start = p.i
                    parameters.append(p.type())
                    if self.signature(parameters[-1], menv, True) == 'V':
                        raise ValueError('Parameter cannot have void type')
                    varargs = '...' in p.tokens[parameter_start:p.i]
                    if p.peek() == ',':
                        if varargs:
                            raise ValueError('Varargs parameter must be last')
                        p.pop()
                        if p.peek() == ')':
                            raise ValueError('Trailing parameter comma')
                    elif p.peek() != ')':
                        raise ValueError('Expected comma between parameters')
                p.pop(')')
                throws = []
                if p.peek() == 'throws':
                    p.pop()
                    while p.peek() and p.peek() != 'default':
                        throws.append(p.type())
                        if p.peek() == ',':
                            p.pop()
                            if p.peek() in (None, 'default'):
                                raise ValueError('Trailing throws comma')
                        elif p.peek() not in (None, 'default'):
                            raise ValueError('Expected comma between exception types')
                if varargs:
                    flags |= 128
                signature_parameters = parameters.copy()
                if category == 'ctor' and '.' in c.name and (not c.flags & 8):
                    parameters.insert(0, Type(c.package + '.' + c.name.rsplit('.', 1)[0]))
                descriptor = '(' + ''.join((self.signature(t, menv, True) for t in parameters)) + ')' + self.signature(returns, menv, True)
                signature = self.formals(formals, menv) + '(' + ''.join((self.signature(t, menv) for t in signature_parameters)) + ')' + self.signature(returns, menv) + ''.join(('^' + self.signature(t, menv) for t in throws))
                source_descriptor = '(' + ''.join(self.signature(t, menv, True) for t in signature_parameters) + ')' + self.signature(returns, menv, True)
                if signature != source_descriptor:
                    attrs.append(attr('Signature', U2(pool.utf(signature))))
                if throws:
                    attrs.append(attr('Exceptions', U2(len(throws)) + b''.join((U2(pool.cls(self.signature(t, menv, True)[1:-1])) for t in throws))))
                if p.peek() == 'default':
                    attrs.append(attr('AnnotationDefault', annotation_value(returns, raw_text.rsplit(' default ', 1)[1])))
                elif p.peek() is not None:
                    raise ValueError('Unexpected tokens after method declaration')
                if not flags & (1024 | 256):
                    slots = (0 if flags & 8 else 1) + sum((2 if self.signature(t, menv, True) in ('J', 'D') else 1 for t in parameters))
                    attrs.append(attr('Code', U2(1) + U2(slots) + U4(2) + bytes((1, 191)) + U2(0) + U2(0)))
                methods.append(member(flags, name, descriptor, attrs))
            except Exception as e:
                raise ValueError(f'{line_number}: {line}') from e
        if c.kind == 'enum':
            for name, desc, slots in [('values', '()[L' + c.binary() + ';', 0), ('valueOf', '(Ljava/lang/String;)L' + c.binary() + ';', 1)]:
                methods.append(member(9, name, desc, [attr('Code', U2(1) + U2(slots) + U4(2) + bytes((1, 191)) + U2(0) + U2(0))]))
        inner = []
        for other in self.classes.values():
            if '.' in other.name and (other.full() == c.full() or other.package + '.' + other.name.rsplit('.', 1)[0] == c.full()):
                outer = other.package + '.' + other.name.rsplit('.', 1)[0]
                flags = other.flags
                if other.kind in ('interface', '@interface'):
                    flags |= 512 | 1024 | 8
                if other.kind == '@interface':
                    flags |= 8192
                if other.kind == 'enum':
                    flags |= 16384 | 16 | 8
                inner.append(U2(pool.cls(other.binary())) + U2(pool.cls(self.binary(outer))) + U2(pool.utf(other.name.rsplit('.', 1)[1])) + U2(flags))
        if inner:
            attributes.append(attr('InnerClasses', U2(len(inner)) + b''.join(inner)))
        signature = self.formals(c.formals, env) + self.signature(c.superclass, env) + ''.join((self.signature(t, env) for t in c.interfaces))
        if c.full() != 'java.lang.Object':
            attributes.append(attr('Signature', U2(pool.utf(signature))))
        flags = c.flags & ~(2 | 4 | 8)
        if c.flags & 4:
            flags |= 1
        if c.kind in ('interface', '@interface'):
            flags |= 512 | 1024
        else:
            flags |= 32
        if c.kind == '@interface':
            flags |= 8192
        if c.kind == 'enum':
            flags |= 16384 | 16
        this = pool.cls(c.binary())
        superclass = 0 if c.full() == 'java.lang.Object' else pool.cls(self.binary(c.superclass.name))
        interfaces = [pool.cls(self.binary(t.name)) for t in c.interfaces]
        body = U2(flags) + U2(this) + U2(superclass) + U2(len(interfaces)) + b''.join((U2(i) for i in interfaces)) + U2(len(fields)) + b''.join(fields) + U2(len(methods)) + b''.join(methods) + U2(len(attributes)) + b''.join(attributes)
        return bytes.fromhex('cafebabe') + U2(0) + U2(52) + pool.serialize() + body

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--base64', action='store_true', help='Decode a Gitiles TEXT source response')
    args = parser.parse_args()
    classes = load(args.source, args.base64)
    compiler = Compiler(classes)
    args.output.mkdir(parents=True, exist_ok=False)
    for name in sorted(classes):
        cls = classes[name]
        dest = args.output / (cls.binary() + '.class')
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(compiler.emit(cls))
    print('Compiled', len(classes), 'Android API stub classes')
if __name__ == '__main__':
    main()
