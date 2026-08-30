// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title Ancla de raíces diarias — Agente CFDI (tarea 2.7)
/// @notice Publica la raíz de Merkle de un día para que un tercero pueda
///         comprobar la bitácora sin pedirle nada a quien la guarda.
///
/// El contrato es deliberadamente mínimo. Todo lo que hace es dejar constancia
/// pública e inmutable de dos datos: qué día se cerró y con qué raíz. La
/// verificación —recalcular la hoja, recorrer el camino de Merkle, comparar
/// contra esta raíz— ocurre fuera, en el verificador independiente, sin gastar
/// gas y sin depender de nadie.
contract AnclaDeRaices {
    /// @notice Quién puede anclar. Sin esto cualquiera publicaría raíces a
    ///         nombre de este contrato y un tercero no sabría cuál es la buena.
    address public immutable dueno;

    /// @notice La raíz publicada de cada día, indexada por `AAAA-MM-DD`.
    /// @dev Es `bytes32` y no `string` porque una raíz de SHA-256 son 32 bytes
    ///      exactos: guardarla como texto costaría más del doble de gas y
    ///      permitiría escribir algo que no es una raíz.
    mapping(string => bytes32) public raizDelDia;

    /// @notice Cuándo se ancló cada día, en tiempo de bloque.
    mapping(string => uint256) public ancladoEn;

    event RaizAnclada(bytes32 indexed raiz, string dia, uint256 momento);

    error NoEsElDueno();
    error DiaYaAnclado(string dia, bytes32 raizPrevia);
    error RaizVacia();

    constructor() {
        dueno = msg.sender;
    }

    /// @notice Publica la raíz de un día. Un día solo se ancla una vez.
    ///
    /// @dev **Reanclar está prohibido a propósito.** Si un mismo día pudiera
    ///      recibir dos raíces, quien guarda la bitácora podría publicar una,
    ///      reescribir el historial y publicar otra — y un tercero no sabría
    ///      cuál creer. Que el primer anclaje sea definitivo es justo lo que
    ///      hace que el pasado no se pueda cambiar en silencio.
    ///
    ///      El reintento del job diario no choca con esto: el sistema consulta
    ///      antes y, si el día ya está anclado, devuelve la constancia original
    ///      en vez de mandar una segunda transacción.
    function anclar(bytes32 raiz, string calldata dia) external {
        if (msg.sender != dueno) revert NoEsElDueno();
        if (raiz == bytes32(0)) revert RaizVacia();

        bytes32 previa = raizDelDia[dia];
        if (previa != bytes32(0)) revert DiaYaAnclado(dia, previa);

        raizDelDia[dia] = raiz;
        ancladoEn[dia] = block.timestamp;

        emit RaizAnclada(raiz, dia, block.timestamp);
    }

    /// @notice Lo que consulta un tercero: la raíz de un día y cuándo se selló.
    /// @dev Sin `view` externo no habría forma de comprobar sin leer eventos.
    function consultar(string calldata dia)
        external
        view
        returns (bytes32 raiz, uint256 momento)
    {
        return (raizDelDia[dia], ancladoEn[dia]);
    }
}
