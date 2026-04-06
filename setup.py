import pathlib
import setuptools

dependencies = [
    "paramiko",
]

HERE = pathlib.Path(__file__).parent
README = (HERE / "README.md").read_text()

setuptools.setup(
    name="clusterrunner",
    version="1.0.0",
    author="Nghia Vo",
    author_email="nvo@bnl.gov",
    description="GUI software for submitting and managing Python jobs on Slurm Clusters",
    long_description=README,
    long_description_content_type="text/markdown",
    keywords=['Slurm job submission'],
    url="https://github.com/algotom/clusterrunner",
    download_url="https://github.com/algotom/clusterrunner.git",
    license="Apache 2.0",
    platforms="Any",
    packages=setuptools.find_packages(include=["clusterrunner", "clusterrunner.*"]),
    package_data={"clusterrunner.assets": ["ClusterRunner_icon.png"]},
    include_package_data=True,
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: Apache Software License",
        "Intended Audience :: Science/Research",
        "Operating System :: OS Independent",
        "Natural Language :: English",
        "Topic :: Scientific/Engineering"
    ],
    install_requires=dependencies,
    entry_points={'console_scripts': ['clusterrunner = clusterrunner.main:main']},
    python_requires='>=3.9',
)
