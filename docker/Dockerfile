# Multi-stage production container for cad-extractor-ir
# Part of the La Vinci ecosystem by Saikat Dutta Chowdhury

FROM public.ecr.aws/lambda/python:3.12 AS builder

# Install build dependencies for compiling GNU LibreDWG
RUN dnf install -y \
    gcc \
    gcc-c++ \
    make \
    git \
    tar \
    gzip \
    autoconf \
    automake \
    libtool \
    texinfo \
    libpcre2-devel \
    python3-devel \
    && dnf clean all

WORKDIR /build

# Clone and compile LibreDWG
RUN git clone --depth 1 https://github.com/LibreDWG/libredwg.git && \
    cd libredwg && \
    sh autogen.sh && \
    ./configure --prefix=/opt/libredwg --disable-bindings --enable-json && \
    make -j$(nproc) && \
    make install

# --- Final Runtime Image ---
FROM public.ecr.aws/lambda/python:3.12

# Copy compiled LibreDWG binary & shared libraries
COPY --from=builder /opt/libredwg /usr/local/
RUN ldconfig

WORKDIR /var/task

# Install package dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ /var/task/
COPY docker/lambda_handler.py /var/task/

# Set Lambda handler entry point
CMD ["lambda_handler.handler"]
