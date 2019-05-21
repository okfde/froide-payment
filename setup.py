#!/usr/bin/env python

import os
import re
import codecs

from setuptools import setup, find_packages


def read(*parts):
    filename = os.path.join(os.path.dirname(__file__), *parts)
    with codecs.open(filename, encoding='utf-8') as fp:
        return fp.read()


def find_version(*file_paths):
    version_file = read(*file_paths)
    version_match = re.search(r"^__version__ = ['\"]([^'\"]*)['\"]",
                              version_file, re.M)
    if version_match:
        return version_match.group(1)
    raise RuntimeError("Unable to find version string.")


setup(
    name="froide_payment",
    version=find_version("froide_payment", "__init__.py"),
    url='https://github.com/okfde/froide-payment',
    license='MIT',
    description="Froide payment app",
    long_description='',
    author='Stefan Wehrmeyer',
    author_email='mail@stefanwehrmeyer.com',
    packages=find_packages(),
    install_requires=[
        'django-payments',
        'django-countries',
        'django-prices',
        'prices',
        'stripe',
    ],
    include_package_data=True,
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Framework :: Django',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Topic :: Utilities',
    ],
    zip_safe=False,
)
