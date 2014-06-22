#!/usr/bin/env python

from setuptools import setup

setup(
    name='chainclient',
    version='0.4.0',
    description='A Python client for the Chain API',
    py_modules=['chainclient'],
    author='Spencer Russell',
    author_email='sfr@mit.edu',
    url='http://github.com/ssfrr/chainclient.py',
    license='MIT',
    install_requires=['requests'],
)
