import setuptools


url = "https://github.com/Kurima/econect-i8-utils" 

with open("requirements.txt", encoding="utf-8") as fh:
    requirements = fh.read().splitlines()

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    name="econect-i8-utils-kurima",
    version="0.9.1",
    author="Malik Irain",
    author_email="malik.irain@irit.fr",
    description="A communication suite to allow transfert of large size data using IEEE 802.15.4 with a few examples.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url=url,
    project_urls={
        "Bug Tracker": url + "/issues",
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: POSIX :: Linux",
    ],
    package_dir={"": "src"},
    packages=setuptools.find_packages(where="src"),
    python_requires=">=3.6",
    install_requires=requirements
)
