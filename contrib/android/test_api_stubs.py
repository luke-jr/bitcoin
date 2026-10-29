#!/usr/bin/env python3
# Copyright (c) 2026 The Bitcoin Knots developers
# Distributed under the MIT software license, see the accompanying file COPYING.
"""Check the compile-time API emitter independently of an installed Android SDK."""

import os
import runpy
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

API = runpy.run_path(os.environ.get(
    'ANDROID_API_COMPILER',
    str(Path(__file__).resolve().parents[1] / 'guix/libexec/build-android-api.py'),
))


class ClassFile:
    def __init__(self, data):
        self.data = data
        self.offset = 0
        if self.read('I') != 0xCAFEBABE:
            raise ValueError('Invalid JVM class magic')
        self.version = self.read('HH')
        count = self.read('H')
        self.pool = [None]
        while len(self.pool) < count:
            tag = self.read('B')
            if tag == 1:
                value = self.bytes(self.read('H')).replace(b'\xc0\x80', b'\0').decode('utf-8', 'surrogatepass')
            elif tag in (7, 8):
                value = self.read('H')
            elif tag in (3, 4):
                value = self.bytes(4)
            elif tag in (5, 6):
                value = self.bytes(8)
            else:
                raise ValueError(f'Unexpected constant tag {tag}')
            self.pool.append((tag, value))
            if tag in (5, 6):
                self.pool.append(None)
        self.flags, this, parent = self.read('HHH')
        self.name = self.class_name(this)
        self.parent = self.class_name(parent) if parent else None
        self.interfaces = [self.class_name(self.read('H')) for _ in range(self.read('H'))]
        self.fields = self.members()
        self.methods = self.members()
        self.attributes = self.attributes_at_cursor()
        if self.offset != len(data):
            raise ValueError('Trailing class bytes')

    def bytes(self, length):
        value = self.data[self.offset:self.offset + length]
        self.offset += length
        return value

    def read(self, fmt):
        values = struct.unpack('>' + fmt, self.bytes(struct.calcsize('>' + fmt)))
        return values[0] if len(values) == 1 else values

    def utf(self, index):
        return self.pool[index][1]

    def class_name(self, index):
        return self.utf(self.utf(index))

    def attributes_at_cursor(self):
        result = {}
        for _ in range(self.read('H')):
            name = self.utf(self.read('H'))
            value = self.bytes(self.read('I'))
            if name == 'Signature':
                value = self.utf(struct.unpack('>H', value)[0])
            result[name] = value
        return result

    def members(self):
        result = {}
        for _ in range(self.read('H')):
            flags, name, descriptor = self.read('HHH')
            result[self.utf(name), self.utf(descriptor)] = (flags, self.attributes_at_cursor())
        return result


SPEC = '''// Signature format: 2.0
package java.lang {
  public class Object {
    ctor public Object();
  }
  public final class String {
  }
  public abstract class Enum<E extends java.lang.Enum<E>> {
  }
}
package java.lang.annotation {
  public interface Annotation {
  }
  public enum RetentionPolicy {
    enum_constant public static final java.lang.annotation.RetentionPolicy CLASS;
    enum_constant public static final java.lang.annotation.RetentionPolicy RUNTIME;
    enum_constant public static final java.lang.annotation.RetentionPolicy SOURCE;
  }
  @java.lang.annotation.Retention(java.lang.annotation.RetentionPolicy.RUNTIME) public @interface Retention {
    method public abstract java.lang.annotation.RetentionPolicy value();
  }
}
package example {
  @java.lang.annotation.Retention(java.lang.annotation.RetentionPolicy.RUNTIME) public @interface Mark {
    method public abstract String value() default "default";
  }
  @java.lang.annotation.Retention(java.lang.annotation.RetentionPolicy.SOURCE) public @interface SourceMark {
  }
  @example.Mark("x=y") @example.SourceMark public class Outer<T> {
    ctor public Outer();
    method public T identity(T);
    method public static void varargs(String...);
    field public static final long MAX = 9223372036854775807L;
    field public static final String TEXT = "hi\\u0000\\ud83d\\ude00";
    field public static final float NAN = (0.0f/0.0f);
  }
  public class Outer.Inner {
    ctor public Outer.Inner(int);
  }
  public static interface Outer.Callback<V> {
    method public V call();
    method public default void reset();
  }
}
'''


class ApiStubTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / 'api.txt'
        self.source.write_text(SPEC)
        self.classes = API['load'](self.source)
        self.compiler = API['Compiler'](self.classes)

    def emit(self, name):
        return ClassFile(self.compiler.emit(self.classes[name]))

    def test_descriptors_and_generic_bounds(self):
        cls = self.emit('example.Outer')
        self.assertEqual(cls.version, (0, 52))
        self.assertEqual(cls.attributes['Signature'], '<T:Ljava/lang/Object;>Ljava/lang/Object;')
        _, attrs = cls.methods['identity', '(Ljava/lang/Object;)Ljava/lang/Object;']
        self.assertEqual(attrs['Signature'], '(TT;)TT;')
        flags, _ = cls.methods['varargs', '([Ljava/lang/String;)V']
        self.assertTrue(flags & 0x80)

    def test_implicit_outer_constructor_and_nested_names(self):
        cls = self.emit('example.Outer.Inner')
        self.assertEqual(cls.name, 'example/Outer$Inner')
        self.assertIn(('<init>', '(Lexample/Outer;I)V'), cls.methods)
        self.assertIn('InnerClasses', cls.attributes)

    def test_interface_abstract_and_default_methods(self):
        cls = self.emit('example.Outer.Callback')
        flags, attrs = cls.methods['call', '()Ljava/lang/Object;']
        self.assertTrue(flags & 0x400)
        self.assertNotIn('Code', attrs)
        flags, attrs = cls.methods['reset', '()V']
        self.assertFalse(flags & 0x400)
        self.assertIn('Code', attrs)

    def test_annotations_respect_retention_and_defaults(self):
        cls = self.emit('example.Outer')
        attribute = cls.attributes['RuntimeVisibleAnnotations']
        self.assertEqual(struct.unpack_from('>H', attribute)[0], 1)
        self.assertNotIn('RuntimeInvisibleAnnotations', cls.attributes)
        mark = self.emit('example.Mark')
        _, attrs = mark.methods['value', '()Ljava/lang/String;']
        tag, index = struct.unpack('>cH', attrs['AnnotationDefault'])
        self.assertEqual(tag, b's')
        self.assertEqual(mark.utf(index), 'default')

    def test_constants_and_modified_utf8(self):
        cls = self.emit('example.Outer')
        _, attrs = cls.fields['MAX', 'J']
        index = struct.unpack('>H', attrs['ConstantValue'])[0]
        self.assertEqual(cls.pool[index], (5, bytes.fromhex('7fffffffffffffff')))
        _, attrs = cls.fields['TEXT', 'Ljava/lang/String;']
        index = struct.unpack('>H', attrs['ConstantValue'])[0]
        self.assertEqual(cls.utf(cls.utf(index)), 'hi\0\ud83d\ude00')
        _, attrs = cls.fields['NAN', 'F']
        index = struct.unpack('>H', attrs['ConstantValue'])[0]
        self.assertEqual(cls.pool[index], (4, bytes.fromhex('7fc00000')))

    def test_enum_implicit_methods(self):
        cls = self.emit('java.lang.annotation.RetentionPolicy')
        self.assertTrue(cls.flags & 0x4000)
        self.assertIn(('values', '()[Ljava/lang/annotation/RetentionPolicy;'), cls.methods)
        self.assertIn(('valueOf', '(Ljava/lang/String;)Ljava/lang/annotation/RetentionPolicy;'), cls.methods)

    def test_deterministic_emission(self):
        first = self.compiler.emit(self.classes['example.Outer'])
        second = API['Compiler'](API['load'](self.source)).emit(self.classes['example.Outer'])
        self.assertEqual(first, second)

    def test_unknown_references_fail(self):
        self.source.write_text(SPEC.replace('method public T identity(T)', 'method public missing.Type identity(T)'))
        classes = API['load'](self.source)
        with self.assertRaisesRegex(ValueError, 'identity'):
            API['Compiler'](classes).emit(classes['example.Outer'])

    def compile_spec(self, spec, name):
        self.source.write_text(spec)
        classes = API['load'](self.source)
        return ClassFile(API['Compiler'](classes).emit(classes[name]))

    def test_generic_inner_constructor_excludes_synthetic_signature_argument(self):
        cls = self.compile_spec(SPEC.replace('Outer.Inner(int)', 'Outer.Inner(T)'), 'example.Outer.Inner')
        _, attrs = cls.methods['<init>', '(Lexample/Outer;Ljava/lang/Object;)V']
        self.assertEqual(attrs['Signature'], '(TT;)V')

    @unittest.skipUnless(shutil.which('javac'), 'javac is required for the independent compiler check')
    def test_javac_resolves_generic_inner_constructor(self):
        self.source.write_text(SPEC.replace('Outer.Inner(int)', 'Outer.Inner(T)'))
        classes = API['load'](self.source)
        compiler = API['Compiler'](classes)
        root = Path(self.directory.name)
        for cls in classes.values():
            if cls.package != 'example':
                continue
            dest = root / (cls.binary() + '.class')
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(compiler.emit(cls))
        client = root / 'Client.java'
        client.write_text('class Client { Object value = new example.Outer<String>().new Inner("ok"); }')
        result = subprocess.run(['javac', '-proc:none', '-classpath', str(root), '-d', str(root), str(client)],
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_static_nested_class_cannot_capture_outer_type_variable(self):
        spec = SPEC.replace('public class Outer.Inner', 'public static class Outer.Inner')
        with self.assertRaisesRegex(ValueError, 'Outer.Inner'):
            self.compile_spec(spec.replace('Outer.Inner(int)', 'Outer.Inner(T)'), 'example.Outer.Inner')

    def test_short_interface_bound_and_erasure(self):
        spec = SPEC.replace('  public final class String {',
                            '  public interface Runnable {\n  }\n  public final class String {')
        cls = self.compile_spec(spec.replace('Outer<T>', 'Outer<T extends Runnable>'), 'example.Outer')
        self.assertEqual(cls.attributes['Signature'], '<T::Ljava/lang/Runnable;>Ljava/lang/Object;')
        _, attrs = cls.methods['identity', '(Ljava/lang/Runnable;)Ljava/lang/Runnable;']
        self.assertEqual(attrs['Signature'], '(TT;)TT;')

    def test_annotation_and_comment_tokens_inside_string_are_literal(self):
        text = 'mail@example.Mark(hello); // literal'
        spec = SPEC.replace('"hi\\u0000\\ud83d\\ude00"', '"' + text + '"')
        cls = self.compile_spec(spec, 'example.Outer')
        _, attrs = cls.fields['TEXT', 'Ljava/lang/String;']
        index = struct.unpack('>H', attrs['ConstantValue'])[0]
        self.assertEqual(cls.utf(cls.utf(index)), text)

    def test_nested_annotation_default_is_not_method_annotation(self):
        spec = SPEC.replace('public @interface SourceMark {',
                            'public @interface SourceMark {\n    method public abstract example.Mark value() default @example.Mark();')
        cls = self.compile_spec(spec, 'example.SourceMark')
        _, attrs = cls.methods['value', '()Lexample/Mark;']
        self.assertEqual(attrs['AnnotationDefault'][:1], b'@')
        self.assertNotIn('RuntimeVisibleAnnotations', attrs)

    def test_default_string_does_not_set_varargs_flag(self):
        cls = self.compile_spec(SPEC.replace('default "default"', 'default "..."'), 'example.Mark')
        flags, _ = cls.methods['value', '()Ljava/lang/String;']
        self.assertFalse(flags & 0x80)

    def test_malformed_declarations_fail(self):
        for before, after in [
            ('Outer<T>', 'Outer<T T>'),
            ('Outer<T>', 'Outer<T,T>'),
            ('identity(T)', 'identity(T T)'),
            ('identity(T)', 'identity(T,)'),
            ('identity(T)', 'identity(void)'),
            ('identity(T)', 'identity(void[])'),
            ('identity(T)', 'identity(@example.Mark T)'),
            ('ctor public Outer();', 'ctor public WrongName();'),
            ('identity(T);', 'identity(T) trailing;'),
            ('identity(T);', 'identity(T)'),
            ('varargs(String...)', 'varargs(String..., int)'),
            ('@example.Mark("x=y")', '@example.Mark("x=y"'),
            ('method public T identity(T);', 'method public T identity(T);\n    method public T identity(T);'),
        ]:
            with self.subTest(after=after), self.assertRaises(ValueError):
                self.compile_spec(SPEC.replace(before, after), 'example.Outer')
        for spec in [SPEC.rstrip()[:-1], SPEC + '}\n', SPEC.replace('package example {', 'package example;')]:
            with self.subTest(spec=spec[-60:]), self.assertRaises(ValueError):
                self.compile_spec(spec, 'example.Outer')

    def test_unsupported_or_duplicate_api_fails(self):
        self.source.write_text(SPEC.replace('format: 2.0', 'format: 3.0'))
        with self.assertRaisesRegex(ValueError, 'format 2.0'):
            API['load'](self.source)
        self.source.write_text(SPEC + 'package example {\n  public class Outer {\n  }\n}\n')
        with self.assertRaisesRegex(ValueError, 'line'):
            API['load'](self.source)


if __name__ == '__main__':
    unittest.main()
