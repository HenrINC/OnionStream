## Installs OnionStream as a python package, mainly used for testing or if you want to use the library in your own project.

from setuptools import setup, find_packages

setup(
    name="OnionStream",
    version="0",
    packages=["onionstream.backend", "onionstream.backend.lib"],
    package_dir={'onionstream.backend': 'backend'},
    install_requires=[
        "fastapi >=0.101",
        "pydantic >=2.0.0, <3.0.0",
        "pycryptodome >=3.0.0, <4.0.0",
    ],
    extras_require={
        "test": [
            # Testing dependencies
            "pytest",
            "pytest-asyncio",
        ],
    },
    author="Henri Questiaux",
    author_email="henri.questiaux@gmail.com",
    description="A short description of your project",
    # long_description=open('README.md').read(),
    # long_description_content_type='text/markdown',
    url="https://github.com/HenrINC/OnionStream",
    classifiers=[
        # Classifiers help users find your project by categorizing it.
        # For a list of valid classifiers, see https://pypi.org/classifiers/
        "Development Status :: 3 - Alpha",  # Or '5 - Production/Stable' or '4 - Beta'
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
    ],
)
