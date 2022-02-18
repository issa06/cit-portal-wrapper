#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from setuptools import setup
import cit_portal_wrapper

def _requires_from_file(filename):
    return open(filename).read().splitlines()

setup(
    name="cit_portal_wrapper",
    version=cit_portal_wrapper.__version__,
    license=cit_portal_wrapper.__license__,
    description="CIT Portal Wrapper",
    author=cit_portal_wrapper.__author__,
    author_email=cit_portal_wrapper.__author_email__,
    url=cit_portal_wrapper.__url__,
    packages=['cit_portal_wrapper'],
    install_requires=_requires_from_file('requirements.txt')
)
