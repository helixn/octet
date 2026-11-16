# OctetHash CUDA solver — compile check + local build.
# CI compiles with Ubuntu's CUDA toolkit (sm_70/sm_86 are enough there);
# locally with CUDA 12.9 you can add ARCH="sm_86,sm_120" etc.

ARCH ?= sm_70,sm_86
NVCC ?= nvcc

CXXFLAGS := -O3 -std=c++17 -gencode arch=compute_70,code=sm_70 \
            -gencode arch=compute_86,code=sm_86

.PHONY: all compile-only clean

all: octet_test

compile-only:
	$(NVCC) $(CXXFLAGS) -c octet.cu -o octet.o

octet_test: octet.cu
	$(NVCC) $(CXXFLAGS) octet.cu -o octet_test

clean:
	rm -f octet.o octet_test
