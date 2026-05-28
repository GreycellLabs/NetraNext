from setuptools import setup, find_packages

with open("requirements.txt") as f:
	install_requires = f.read().strip().split("\n")

# get version from __version__ variable in netranext_client/__init__.py
from netranext_client import __version__ as version

setup(
	name="netranext_client",
	version=version,
	description="Client management app",
	author="meet",
	author_email="meet.vaghasiya@egreycell.com",
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
	install_requires=install_requires
)
